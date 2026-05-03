"""Event handler functions extracted from app.py."""

import os
import sys
from pathlib import Path

from launcher_core.models import GLOBAL_FAILED, GLOBAL_IDLE, GLOBAL_PAUSED, GLOBAL_RUNNING
from launcher_core.process_manager import launch_batch, process_is_running, terminate_process_tree


def on_main_action(app) -> None:
    if app.task_manager.global_state not in {GLOBAL_RUNNING, GLOBAL_PAUSED}:
        start_new_run(app)


def on_secondary_action(app) -> None:
    if process_is_running(app) or app.task_manager.global_state in {GLOBAL_RUNNING, GLOBAL_PAUSED}:
        stop_run(app)
        return
    if app.task_manager.ordered_tasks() or app.batch_target > 0:
        clear_current_run(app)


def start_new_run(app) -> None:
    if app.process and app.process.poll() is None:
        return
    platforms = app._selected_platforms()
    if not platforms:
        app._show_toast("请至少选择一个平台")
        return

    count = app._safe_int(app.count_var.get(), 12)
    workers = app._safe_int(app.workers_var.get(), 3)
    project_key = app.project_var.get()
    from launcher_core.app import _ensure_runtime_project

    _ensure_runtime_project(project_key)
    app.task_manager.reset()
    app.task_manager.global_state = GLOBAL_RUNNING
    app.selected_task_id = None
    app.batch_target = count
    app.batch_saved = 0
    app.batch_errors = 0
    app._persist_current_config()
    launch_batch(app, count, workers, platforms, reset_log=True)


def pause_run(app) -> None:
    app._show_toast("批处理模式下不再支持暂停，请使用停止")


def resume_run(app) -> None:
    app._show_toast("批处理模式下不再支持继续，请重新开始")


def clear_current_run(app) -> None:
    app._cancel_pause_timeout()
    app._clear_pause_file()
    terminate_process_tree(app)
    if app.current_plan_path:
        try:
            Path(app.current_plan_path).unlink(missing_ok=True)
        except Exception:
            pass
    app.task_manager.reset()
    app.process = None
    app.reader_thread = None
    app.selected_task_id = None
    app.start_time = None
    app.current_plan_path = ""
    app.session_log_path = ""
    app.session_log_offset = 0
    app.current_stage = "等待启动"
    app.current_run_label = "待机中"
    app.visual_progress = 0.0
    app.batch_target = 0
    app.batch_saved = 0
    app.batch_errors = 0
    app.footer_status.configure(text="已清空当前批次，可重新开始")
    app._refresh_summary()
    app._refresh_ui_state()
    app._render_tasks()
    app._render_detail()
    app._show_toast("已清空当前批次")


def stop_run(app) -> None:
    app._cancel_pause_timeout()
    app._clear_pause_file()
    terminate_process_tree(app)
    app.task_manager.global_state = GLOBAL_FAILED
    app.batch_errors = max(app.batch_errors, 1)
    app.footer_status.configure(text="当前批次已停止")
    app._show_toast("已停止当前批次")
    app._refresh_ui_state()


def retry_selected_task(app) -> None:
    app._show_toast("批处理模式下已关闭单任务重试")


def copy_selected_task(app) -> None:
    if not app.selected_task_id:
        return
    text = app.task_manager.copy_text(app.selected_task_id)
    if not text:
        app._show_toast("当前任务还没有可复制的内容")
        return
    app.root.clipboard_clear()
    app.root.clipboard_append(text)
    app._show_toast("已复制当前任务内容")


def export_selected_task(app) -> None:
    from tkinter import filedialog

    task = app.task_manager.get_task(app.selected_task_id or "")
    if not task or not task.article_path:
        app._show_toast("当前任务还没有输出文件")
        return
    target = filedialog.asksaveasfilename(
        title="导出任务文件",
        defaultextension=".txt",
        initialfile=Path(task.article_path).name,
        filetypes=[("Text", "*.txt")],
    )
    if not target:
        return

    def _read_text(path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception:
            return ""

    Path(target).write_text(_read_text(task.article_path), encoding="utf-8")
    app._show_toast("导出完成")


def delete_selected_task(app) -> None:
    app._show_toast("批处理模式下已关闭单任务删除")
