"""Process lifecycle management extracted from app.py.

All functions receive ``app`` (the LauncherApp instance) as the first
parameter so they can read/write state and trigger UI refreshes.
"""

import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from launcher_core.models import GLOBAL_FAILED


def launch_batch(app, count: int, workers: int, platforms: list[str], reset_log: bool) -> None:
    from launcher_core.app import PLATFORMS, PROJECTS, _project_dir

    project_key = app.project_var.get()
    project_dir = _project_dir(project_key)
    app.start_time = datetime.now()
    app.current_stage = "关键词扩展"
    app.current_run_label = f"{PROJECTS[project_key]['label']} · {count} 篇"
    app.visual_progress = 0.02
    if reset_log:
        app.session_log_path = ""
        app.session_log_offset = 0
    app._refresh_summary()
    app._refresh_ui_state()
    app.footer_status.configure(text=f"任务启动中 · {app.current_run_label}")

    cmd = _build_launch_cmd(app, project_key, workers, count, platforms)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        app.process = subprocess.Popen(
            cmd,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except Exception as exc:
        app.process = None
        app.task_manager.global_state = GLOBAL_FAILED
        from tkinter import messagebox

        messagebox.showerror(app.APP_TITLE, f"启动失败：{exc}")
        app._refresh_ui_state()
        return

    app.reader_thread = threading.Thread(target=lambda: _read_output(app), daemon=True)
    app.reader_thread.start()
    app._show_toast("任务已开始运行")


def _build_launch_cmd(app, project_key: str, workers: int, count: int, platforms: list[str]) -> list[str]:
    from launcher_core.app import _source_root

    base = [sys.executable]
    if not getattr(sys, "frozen", False):
        base.append(str(_source_root() / "launcher_gui.pyw"))
    cmd = base + [
        "--worker",
        "--project",
        project_key,
        "--workers",
        str(workers),
        "--count",
        str(count),
        "--platforms",
        ",".join(platforms),
        "--generation-mode",
        app._generation_mode_key(),
    ]
    return cmd


def _read_output(app) -> None:
    try:
        if app.process and app.process.stdout:
            for line in app.process.stdout:
                app.queue.put(("line", line.rstrip("\r\n")))
    finally:
        if app.process:
            app.queue.put(("done", app.process.wait()))


def process_is_running(app) -> bool:
    return bool(app.process and app.process.poll() is None)


def terminate_process_tree(app) -> None:
    if not app.process:
        return
    if app.process.poll() is not None:
        app.process = None
        return
    pid = app.process.pid
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creationflags,
        )
    except Exception:
        try:
            app.process.terminate()
        except Exception:
            pass
