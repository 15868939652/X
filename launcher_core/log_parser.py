"""Runtime log parsing and session log sync extracted from app.py.

All functions receive ``app`` (the LauncherApp instance) as the first
parameter so they can read/write state and trigger UI refreshes.
"""

import json
import os
import re

from launcher_core.models import GLOBAL_COMPLETED, GLOBAL_FAILED


def extract_global_stage(line: str) -> str:
    STAGE_MAPPING = {
        "扩展长尾词": "关键词扩展",
        "长尾词": "关键词扩展",
        "生成初稿": "首稿生成",
        "初稿完成": "首稿生成",
        "去AI化完成": "去AI化",
        "质量评分": "评分",
        "重新评分": "评分",
        "[SAVE]": "保存",
    }
    for key, value in STAGE_MAPPING.items():
        if key in line:
            return value
    return ""


def capture_log_path(app, line: str) -> None:
    match = re.search(r"(logs[\\/]+generation_\d{8}_\d{6}\.jsonl)", line)
    if not match or app.session_log_path:
        return
    from launcher_core.app import _project_dir

    app.session_log_path = str(_project_dir(app.project_var.get()) / match.group(1).replace("\\", os.sep).replace("/", os.sep))
    app.session_log_offset = 0


def handle_line(app, line: str) -> None:
    if not line.strip():
        return
    capture_log_path(app, line)
    app.current_stage = extract_global_stage(line) or app.current_stage
    app.task_manager.apply_runtime_line(line)
    if "[SAVE]" in line or "已保存" in line:
        app.batch_saved = min(app.batch_target, app.batch_saved + 1)
    if "[ERR]" in line or "失败" in line:
        app.batch_errors += 1
    app._refresh_summary()
    app._schedule_task_refresh()


def discover_log_path(app) -> str:
    from launcher_core.app import _project_dir

    project_logs = _project_dir(app.project_var.get()) / "logs"
    if not project_logs.exists() or not app.start_time:
        return ""
    candidates = sorted(project_logs.glob("generation_*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    threshold = app.start_time.timestamp() - 3
    for item in candidates:
        if item.stat().st_mtime >= threshold:
            return str(item)
    return ""


def consume_session_log(app) -> None:
    try:
        with open(app.session_log_path, "r", encoding="utf-8") as f:
            f.seek(app.session_log_offset)
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                from launcher_core.app import _project_dir

                app.task_manager.apply_record(record, str(_project_dir(app.project_var.get())))
            app.session_log_offset = f.tell()
    except OSError:
        return
    app._refresh_summary()
    app._schedule_task_refresh()


def handle_process_done(app, code: int) -> None:
    app._cancel_pause_timeout()
    app._clear_pause_file()
    consume_session_log(app)
    app.process = None
    if code == 0:
        app.task_manager.global_state = GLOBAL_COMPLETED
        app.visual_progress = 1.0
        app.batch_saved = max(app.batch_saved, app.batch_target)
    else:
        app.task_manager.global_state = GLOBAL_FAILED
    app.footer_status.configure(text="任务完成" if code == 0 else f"任务结束 · 退出码 {code}")
    app._refresh_summary()
    app._refresh_ui_state()
    app._render_tasks()
    app._render_detail()
    app._show_toast("本轮任务已结束")
    app._show_done_popup()


def sync_session_log(app) -> None:
    if app.session_log_path:
        if os.path.exists(app.session_log_path):
            consume_session_log(app)
    elif not app.process:
        app.session_log_path = discover_log_path(app)
        if app.session_log_path and os.path.exists(app.session_log_path):
            consume_session_log(app)
    app.root.after(700, lambda: sync_session_log(app))


def poll_queue(app) -> None:
    import queue

    while True:
        try:
            kind, payload = app.queue.get_nowait()
        except queue.Empty:
            break
        if kind == "line":
            handle_line(app, payload)
        elif kind == "done":
            handle_process_done(app, payload)
    app.root.after(100, lambda: poll_queue(app))
