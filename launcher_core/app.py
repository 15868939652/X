from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading

from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from launcher_core.config_manager import ConfigManager
from launcher_core.events.handlers import (
    clear_current_run,
    copy_selected_task,
    delete_selected_task,
    export_selected_task,
    on_main_action,
    on_secondary_action,
    retry_selected_task,
    start_new_run,
    stop_run,
)
from launcher_core.log_parser import (
    capture_log_path,
    consume_session_log,
    discover_log_path,
    extract_global_stage,
    handle_line,
    handle_process_done,
    poll_queue,
    sync_session_log,
)
from launcher_core.models import (
    GLOBAL_COMPLETED,
    GLOBAL_FAILED,
    GLOBAL_IDLE,
    GLOBAL_PAUSED,
    GLOBAL_RUNNING,
    TASK_FAILED,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_SUCCESS,
    Task,
)
from launcher_core.process_manager import (
    launch_batch,
    process_is_running,
    terminate_process_tree,
    _build_launch_cmd,
    _read_output,
)
from launcher_core.task_manager import TaskManager
from launcher_core.ui.themes import PROJECTS, apply_theme
from launcher_core.ui.widgets import bind_click, entry_row, panel, subtext, title

APP_TITLE = "多平台文章生成器"
APP_SUBTITLE = "内容生产控制系统"
PLATFORMS = [
    ("zhihu", "知乎"),
    ("sohu", "搜狐"),
    ("baijiahao", "百家号"),
    ("toutiao", "头条"),
]
PLATFORM_LABELS = dict(PLATFORMS)
GENERATION_MODE_LABELS = {
    "fast": "快速模式",
    "quality": "稳健质量模式",
    "one_shot": "一稿直出模式",
}
GENERATION_MODE_KEYS = {label: key for key, label in GENERATION_MODE_LABELS.items()}
STATUS_LABELS = {
    TASK_PENDING: "待执行",
    TASK_RUNNING: "运行中",
    TASK_SUCCESS: "已完成",
    TASK_FAILED: "失败",
}
GLOBAL_ACTION_LABELS = {
    GLOBAL_IDLE: "开始生成",
    GLOBAL_RUNNING: "运行中",
    GLOBAL_PAUSED: "继续",
    GLOBAL_COMPLETED: "再生成",
    GLOBAL_FAILED: "重新开始",
}
GLOBAL_STATE_LABELS = {
    GLOBAL_IDLE: "待机中",
    GLOBAL_RUNNING: "运行中",
    GLOBAL_PAUSED: "已暂停",
    GLOBAL_COMPLETED: "已完成",
    GLOBAL_FAILED: "需处理",
}
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

STAGE_PROGRESS = {
    "等待启动": 0.0,
    "等待执行": 0.0,
    "等待继续": 0.02,
    "关键词扩展": 0.16,
    "首稿生成": 0.46,
    "去AI化": 0.68,
    "评分": 0.84,
    "保存": 0.94,
    "保存完成": 1.0,
    "任务失败": 1.0,
}


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", _source_root()))


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for item in src.rglob("*"):
        relative = item.relative_to(src)
        if "__pycache__" in relative.parts:
            continue
        target = dst / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _ensure_runtime_project(project_key: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    runtime_root = _runtime_root()
    bundle_root = _bundle_root()
    _copy_tree(bundle_root / "shared", runtime_root / "shared")
    _copy_tree(bundle_root / "projects" / project_key, runtime_root / "projects" / project_key)


def _project_dir(project_key: str) -> Path:
    if getattr(sys, "frozen", False):
        return _runtime_root() / "projects" / project_key
    return _source_root() / "projects" / project_key


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_root()


def _read_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


class LauncherApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(APP_TITLE)
        self.root.geometry("1460x900")
        self.root.minsize(1240, 800)
        self.root.configure(fg_color="#F4F7FB")

        self.config_manager = ConfigManager()
        self.task_manager = TaskManager()
        self.process: subprocess.Popen | None = None
        self.reader_thread: threading.Thread | None = None
        self.queue: queue.Queue = queue.Queue()
        self.start_time: datetime | None = None
        self.session_log_path = ""
        self.session_log_offset = 0
        self.current_stage = "等待启动"
        self.current_run_label = "待机中"
        self.visual_progress = 0.0
        self.batch_target = 0
        self.batch_saved = 0
        self.batch_errors = 0
        self._ui_refresh_scheduled = False
        self._task_cards: dict[str, dict] = {}
        self.current_plan_path = ""
        self.selected_task_id: str | None = None


        self._toast_after_id = None
        self._pause_file_path = ""
        self._pause_timeout_id = None
        self._last_multi_count = "12"

        self.project_var = tk.StringVar(value="yiwu_yicheng")
        self.count_var = tk.StringVar(value="12")
        self.workers_var = tk.StringVar(value="2")
        self.generation_mode_var = tk.StringVar(value=GENERATION_MODE_LABELS["fast"])
        self.platform_vars = {key: tk.BooleanVar(value=True) for key, _ in PLATFORMS}


        _ensure_runtime_project(self.project_var.get())
        self._build_ui()
        self._load_initial_config()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_queue)
        self.root.after(700, self._sync_session_log)
        self.root.after(1000, self._tick_runtime)
        self.root.after(120, self._animate_progress)

    def _cfg(self) -> dict:
        return PROJECTS[self.project_var.get()]

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self._build_topbar()
        self._build_sidebar()
        self._build_main()
        self._build_footer()

    def _panel(self, parent, fg="#FFFFFF", border="#D8E3EE", radius=16):
        return panel(parent, fg=fg, border=border, radius=radius)

    def _title(self, parent, text: str, size: int = 13):
        return title(parent, text=text, size=size)

    def _subtext(self, parent, text: str, wrap: int = 270):
        return subtext(parent, text=text, wrap=wrap)

    def _build_topbar(self) -> None:
        top = ctk.CTkFrame(self.root, fg_color="#FFFFFF", corner_radius=0, height=64, border_width=1, border_color="#E2E8F0")
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)
        top.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=(20, 14), pady=10)
        self.brand_badge = ctk.CTkLabel(
            brand,
            text="X",
            width=38,
            height=38,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=18, weight="bold"),
            text_color="#FFFFFF",
        )
        self.brand_badge.pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            brand_text,
            text=APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=18, weight="bold"),
            text_color="#0F172A",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text=APP_SUBTITLE,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=10),
            text_color="#94A3B8",
        ).pack(anchor="w")

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e", padx=(0, 16), pady=10)
        ctk.CTkLabel(controls, text="项目选择", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#64748B").grid(row=0, column=0, padx=(0, 8))
        self.project_combo = ctk.CTkComboBox(
            controls,
            width=156,
            height=36,
            values=[cfg["label"] for cfg in PROJECTS.values()],
            state="readonly",
            command=self._on_combo_project_change,
        )
        self.project_combo.grid(row=0, column=1, padx=(0, 10))

        self.main_btn = ctk.CTkButton(
            controls,
            text=GLOBAL_ACTION_LABELS[GLOBAL_IDLE],
            width=120,
            height=38,
            corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=13, weight="bold"),
            command=self.on_main_action,
        )
        self.main_btn.grid(row=0, column=2, padx=(0, 8))
        self.stop_btn = ctk.CTkButton(
            controls,
            text="停止",
            width=88,
            height=38,
            corner_radius=12,
            command=self.on_secondary_action,
        )
        self.stop_btn.grid(row=0, column=3)

    def _build_sidebar(self) -> None:
        shell = ctk.CTkFrame(self.root, fg_color="#F8FAFC", width=300, corner_radius=0)
        shell.grid(row=1, column=0, sticky="nsew")
        shell.grid_propagate(False)
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        sidebar = ctk.CTkScrollableFrame(shell, width=280, fg_color="transparent")
        sidebar.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar = sidebar

        intro = self._panel(sidebar)
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        intro_inner = ctk.CTkFrame(intro, fg_color="transparent")
        intro_inner.pack(fill="x", padx=14, pady=14)
        self._title(intro_inner, "内容生产工作台").pack(anchor="w")
        self._subtext(
            intro_inner,
            "医疗内容批量生成、过程质控与结果交付。支持任务追踪、模板复用、失败重试和批次复盘。",
            wrap=244,
        ).pack(anchor="w", pady=(6, 0))

        project_card = self._panel(sidebar)
        project_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        inner = ctk.CTkFrame(project_card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)
        self._title(inner, "1. 项目选择").pack(anchor="w")
        self.project_radios = {}
        for index, (key, cfg) in enumerate(PROJECTS.items()):
            radio = ctk.CTkRadioButton(inner, text=cfg["label"], variable=self.project_var, value=key, command=self.switch_project)
            radio.pack(anchor="w", pady=(10 if index == 0 else 8, 0))
            self.project_radios[key] = radio

        platform_card = self._panel(sidebar)
        platform_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        inner = ctk.CTkFrame(platform_card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)
        self._title(inner, "2. 平台选择").pack(anchor="w")
        self._subtext(inner, "支持一键全平台，也支持一键切到单个平台。").pack(anchor="w", pady=(8, 0))

        self.platform_all_btn = ctk.CTkButton(
            inner,
            text="全平台生成",
            height=32,
            corner_radius=12,
            command=lambda: self._apply_platform_preset("all"),
        )
        self.platform_all_btn.pack(fill="x", pady=(10, 0))

        single_row = ctk.CTkFrame(inner, fg_color="transparent")
        single_row.pack(fill="x", pady=(8, 0))
        single_row.grid_columnconfigure((0, 1), weight=1, uniform="platform_single")
        self.single_platform_buttons: dict[str, ctk.CTkButton] = {}
        for index, (key, label) in enumerate(PLATFORMS):
            btn = ctk.CTkButton(
                single_row,
                text=label,
                height=30,
                corner_radius=12,
                command=lambda item=key: self._apply_platform_preset(item),
            )
            btn.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0, 4) if index % 2 == 0 else (4, 0),
                pady=(0, 6) if index < 2 else (0, 0),
            )
            self.single_platform_buttons[key] = btn

        self.platform_checks = {}
        for index, (key, label) in enumerate(PLATFORMS):
            cb = ctk.CTkCheckBox(inner, text=label, variable=self.platform_vars[key], onvalue=True, offvalue=False, command=self._on_platform_toggle)
            cb.pack(anchor="w", pady=(10 if index == 0 else 8, 0))
            self.platform_checks[key] = cb
        self.platform_hint = self._subtext(inner, "")
        self.platform_hint.pack(anchor="w", pady=(10, 0))

        settings_card = self._panel(sidebar)
        settings_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        inner = ctk.CTkFrame(settings_card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)
        self._title(inner, "3. 生成设置").pack(anchor="w")
        self.mode_combo = ctk.CTkComboBox(
            inner,
            width=240,
            height=36,
            values=list(GENERATION_MODE_LABELS.values()),
            variable=self.generation_mode_var,
            state="readonly",
            command=lambda _value: self._on_generation_mode_change(),
        )
        self.mode_combo.pack(anchor="w", pady=(10, 0))
        self.workers_entry = self._entry_row(inner, "并发数", self.workers_var)
        self.side_count_entry = self._entry_row(inner, "生成数量", self.count_var)
        self.count_entry = self.side_count_entry
        self.settings_hint = self._subtext(inner, "")
        self.settings_hint.pack(anchor="w", pady=(12, 0))

        tool_card = self._panel(sidebar)
        tool_card.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        inner = ctk.CTkFrame(tool_card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)
        self._title(inner, "快捷入口").pack(anchor="w")
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x", pady=(10, 0))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="tool")
        self.btn_latest_dir = ctk.CTkButton(grid, text="最新批次", height=34, corner_radius=12, command=self.open_latest_output_folder)
        self.btn_latest_dir.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.btn_txt_dir = ctk.CTkButton(grid, text="TXT目录", height=34, corner_radius=12, command=self.open_latest_txt_folder)
        self.btn_txt_dir.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        self.btn_txt_file = ctk.CTkButton(grid, text="TXT文件", height=34, corner_radius=12, command=self.open_latest_txt_file)
        self.btn_txt_file.grid(row=1, column=0, sticky="ew", padx=(0, 4), columnspan=2)

    def _entry_row(self, parent, label: str, variable: tk.StringVar):
        return entry_row(parent, label=label, variable=variable)

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.grid(row=1, column=1, sticky="nsew", padx=(16, 16), pady=(16, 10))
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)
        self.main = main

        self._build_stats(main)
        self._build_summary(main)
        self._build_bottom(main)

    def _build_stats(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for idx in range(4):
            row.grid_columnconfigure(idx, weight=1, uniform="stats")

        self.stats_cards = {}
        stat_configs = [
            ("success", "已完成", "#22C55E"),
            ("failed", "失败数", "#EF4444"),
            ("progress", "进度", "#3B82F6"),
            ("runtime", "运行时间", "#8B5CF6"),
        ]
        for idx, (key, title, accent_color) in enumerate(stat_configs):
            card = self._panel(row, radius=14)
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0 if idx == 3 else 6))
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=12)
            # Subtle color dot indicator
            dot = ctk.CTkLabel(inner, text="", width=8, height=8, corner_radius=4, fg_color=accent_color)
            ctk.CTkLabel(inner, text=title, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"), text_color="#475569").pack(anchor="w", pady=(0, 6))
            value = ctk.CTkLabel(inner, text="0", font=ctk.CTkFont(family="Segoe UI Semibold", size=26, weight="bold"), text_color="#0F172A")
            value.pack(anchor="w")
            hint = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#94A3B8")
            hint.pack(anchor="w", pady=(2, 0))
            self.stats_cards[key] = {"value": value, "hint": hint}

    def _build_summary(self, parent) -> None:
        card = self._panel(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)

        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x")
        self._title(head, "文案生成器运行总览").pack(side="left")
        self.batch_state_chip = ctk.CTkLabel(
            head,
            text=GLOBAL_STATE_LABELS[GLOBAL_IDLE],
            corner_radius=999,
            padx=12,
            pady=6,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
        )
        self.batch_state_chip.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(inner, height=14, corner_radius=999)
        self.progress_bar.pack(fill="x", pady=(14, 10))
        self.progress_bar.set(0)

        meta = ctk.CTkFrame(inner, fg_color="transparent")
        meta.pack(fill="x")
        self.progress_meta = ctk.CTkLabel(meta, text="等待启动", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91")
        self.progress_meta.pack(side="left")
        self.progress_value = ctk.CTkLabel(meta, text="0%", font=ctk.CTkFont(family="Segoe UI Semibold", size=12, weight="bold"), text_color="#133248")
        self.progress_value.pack(side="right")

        summary_grid = ctk.CTkFrame(inner, fg_color="transparent")
        summary_grid.pack(fill="x", pady=(14, 0))
        summary_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="sum")
        self.result_boxes = {}
        result_defs = [
            ("excellent", "优秀 90+"),
            ("qualified", "合格 70-89"),
            ("rewrite", "需优化"),
        ]
        for idx, (key, label) in enumerate(result_defs):
            box = self._panel(summary_grid, fg="#F9FBFE", radius=14)
            box.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0 if idx == 2 else 6))
            box_inner = ctk.CTkFrame(box, fg_color="transparent")
            box_inner.pack(fill="x", padx=14, pady=14)
            ctk.CTkLabel(box_inner, text=label, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91").pack(anchor="w")
            value = ctk.CTkLabel(box_inner, text="0", font=ctk.CTkFont(family="Segoe UI Semibold", size=24, weight="bold"), text_color="#133248")
            value.pack(anchor="w", pady=(6, 0))
            self.result_boxes[key] = value

        self.batch_report = ctk.CTkLabel(
            inner,
            text="批次总结会在运行后自动更新，帮助快速判断可交付内容与需返工任务。",
            justify="left",
            wraplength=920,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#6B8195",
        )
        self.batch_report.pack(anchor="w", pady=(12, 0))

    def _build_bottom(self, parent) -> None:
        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.grid(row=2, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=1)
        split.grid_columnconfigure(1, weight=1)
        split.grid_rowconfigure(0, weight=1)

        self.tasks_card = self._panel(split)
        self.tasks_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.tasks_card.grid_rowconfigure(1, weight=1)
        self.tasks_card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self.tasks_card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        head.grid_columnconfigure(0, weight=1)
        title_wrap = ctk.CTkFrame(head, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")
        self._title(title_wrap, "任务列表").pack(anchor="w")
        self._subtext(title_wrap, "每篇文章都是独立任务，可单独查看、重试、复制和导出。", wrap=520).pack(anchor="w", pady=(4, 0))
        self.task_counter = ctk.CTkLabel(head, text="0 / 0", font=ctk.CTkFont(family="Segoe UI Semibold", size=14, weight="bold"), text_color="#617A91")
        self.task_counter.grid(row=0, column=1, sticky="e")
        self.task_list = ctk.CTkScrollableFrame(self.tasks_card, fg_color="transparent")
        self.task_list.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.task_list.grid_columnconfigure(0, weight=1)

        self.detail_card = self._panel(split)
        self.detail_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.detail_card.grid_rowconfigure(1, weight=1)
        self.detail_card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self.detail_card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        head.grid_columnconfigure(0, weight=1)
        title_wrap = ctk.CTkFrame(head, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")
        self._title(title_wrap, "任务详情").pack(anchor="w")
        self._subtext(title_wrap, "内容预览、调用记录、错误原因和单任务操作都集中在这里。", wrap=520).pack(anchor="w", pady=(4, 0))

        actions = ctk.CTkFrame(head, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.task_retry_btn = ctk.CTkButton(actions, text="重试", width=74, height=34, corner_radius=12, command=self.retry_selected_task)
        self.task_retry_btn.grid(row=0, column=0, padx=(0, 6))
        self.task_copy_btn = ctk.CTkButton(actions, text="复制", width=74, height=34, corner_radius=12, command=self.copy_selected_task)
        self.task_copy_btn.grid(row=0, column=1, padx=6)
        self.task_export_btn = ctk.CTkButton(actions, text="导出", width=74, height=34, corner_radius=12, command=self.export_selected_task)
        self.task_export_btn.grid(row=0, column=2, padx=6)
        self.task_delete_btn = ctk.CTkButton(actions, text="删除", width=74, height=34, corner_radius=12, command=self.delete_selected_task)
        self.task_delete_btn.grid(row=0, column=3, padx=(6, 0))

        self.detail_body = ctk.CTkScrollableFrame(self.detail_card, fg_color="transparent")
        self.detail_body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.detail_body.grid_columnconfigure(0, weight=1)

        card = self._panel(self.detail_body, fg="#FBFDFF", radius=14)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self.detail_title_label = ctk.CTkLabel(inner, text="请选择任务查看详情", font=ctk.CTkFont(family="Segoe UI Semibold", size=18, weight="bold"), text_color="#133248")
        self.detail_title_label.pack(anchor="w")
        self.detail_subtitle = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91")
        self.detail_subtitle.pack(anchor="w", pady=(6, 0))
        self.detail_meta = ctk.CTkLabel(inner, text="", justify="left", wraplength=760, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91")
        self.detail_meta.pack(anchor="w", pady=(12, 0))

        metrics = ctk.CTkFrame(inner, fg_color="transparent")
        metrics.pack(fill="x", pady=(14, 0))
        metrics.grid_columnconfigure((0, 1, 2), weight=1, uniform="m")
        self.detail_metric_labels = {}
        metric_defs = [
            ("score", "最终得分"),
            ("tokens", "Token 消耗"),
            ("result", "推荐判断"),
        ]
        for idx, (key, label) in enumerate(metric_defs):
            box = self._panel(metrics, fg="#FFFFFF", radius=12)
            box.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0 if idx == 2 else 6))
            box_inner = ctk.CTkFrame(box, fg_color="transparent")
            box_inner.pack(fill="x", padx=14, pady=12)
            ctk.CTkLabel(box_inner, text=label, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#617A91").pack(anchor="w")
            value = ctk.CTkLabel(box_inner, text="--", font=ctk.CTkFont(family="Segoe UI Semibold", size=18, weight="bold"), text_color="#133248")
            value.pack(anchor="w", pady=(6, 0))
            self.detail_metric_labels[key] = value

        card = self._panel(self.detail_body, fg="#FBFDFF", radius=14)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)
        self._title(inner, "内容预览").pack(anchor="w")
        self.preview_box = ctk.CTkTextbox(inner, height=210, corner_radius=12, wrap="word")
        self.preview_box.pack(fill="both", expand=True, pady=(12, 0))

        card = self._panel(self.detail_body, fg="#FBFDFF", radius=14)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self._title(inner, "任务时间线").pack(anchor="w")
        self.timeline_box = ctk.CTkTextbox(inner, height=150, corner_radius=12, wrap="word")
        self.timeline_box.pack(fill="x", pady=(12, 0))

        card = self._panel(self.detail_body, fg="#FBFDFF", radius=14)
        card.grid(row=3, column=0, sticky="ew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self._title(inner, "LLM 调用记录").pack(anchor="w")
        self.calls_box = ctk.CTkTextbox(inner, height=170, corner_radius=12, wrap="word")
        self.calls_box.pack(fill="x", pady=(12, 0))

    def _build_footer(self) -> None:
        sep = ctk.CTkFrame(self.root, height=1, fg_color="#E2E8F0", corner_radius=0)
        sep.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 0))
        footer = ctk.CTkFrame(self.root, fg_color="transparent")
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", padx=18, pady=(6, 8))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_status = ctk.CTkLabel(footer, text="待机中 · 准备就绪", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#94A3B8")
        self.footer_status.grid(row=0, column=0, sticky="w")
        self.toast_label = ctk.CTkLabel(footer, text="", corner_radius=999, padx=14, pady=6, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"))
        self.toast_label.grid(row=0, column=1, sticky="e")

    def _load_initial_config(self) -> None:
        payload = self.config_manager.load_last_config()
        if payload:
            self._apply_config_payload(payload, save_last=False)
        self.project_combo.set(PROJECTS[self.project_var.get()]["label"])
        self._refresh_hints()
        self._refresh_ui_state()
        self._render_tasks()
        self._render_detail()

    def _refresh_hints(self) -> None:
        selected = [label for key, label in PLATFORMS if self.platform_vars[key].get()]
        if len(selected) == len(PLATFORMS):
            platform_desc = "全平台生成"
        elif len(selected) == 1:
            platform_desc = f"单平台：{selected[0]}（生成数量已切换为 3）"
        elif selected:
            platform_desc = "自定义组合：" + "、".join(selected)
        else:
            platform_desc = "未选择"
        self.platform_hint.configure(text=f"当前平台：{platform_desc}")
        mode_hint = {
            "fast": "快速模式：沿用原豆包链路，适合稳定批量生成。",
            "quality": "稳健质量模式：初稿、一次评分、必要时一次改写。",
            "one_shot": "一稿直出模式：跳过扩词和复评，单篇成功路径只调用一次模型。",
        }[self._generation_mode_key()]
        self.settings_hint.configure(text=mode_hint)

    def _on_combo_project_change(self, selected_label: str) -> None:
        for key, cfg in PROJECTS.items():
            if cfg["label"] == selected_label:
                self.project_var.set(key)
                break
        self.switch_project()

    def switch_project(self) -> None:
        _ensure_runtime_project(self.project_var.get())
        self.project_combo.set(self._cfg()["label"])
        self._apply_theme()
        self._refresh_hints()
        self._persist_current_config()

    def _apply_theme(self) -> None:
        apply_theme(self)

    def _collect_config_payload(self) -> dict:
        return {
            "project": self.project_var.get(),
            "count": self.count_var.get(),
            "workers": self.workers_var.get(),
            "generation_mode": self._generation_mode_key(),
            "platforms": [key for key, _ in PLATFORMS if self.platform_vars[key].get()],
        }

    def _apply_config_payload(self, payload: dict, save_last: bool = True) -> None:
        project = payload.get("project", self.project_var.get())
        if project in PROJECTS:
            self.project_var.set(project)
        self.count_var.set(str(payload.get("count", self.count_var.get())))
        self.workers_var.set(str(payload.get("workers", self.workers_var.get())))
        generation_mode = self._generation_mode_key(payload.get("generation_mode", self.generation_mode_var.get()))
        self.generation_mode_var.set(GENERATION_MODE_LABELS.get(generation_mode, GENERATION_MODE_LABELS["fast"]))
        selected = set(payload.get("platforms", [key for key, _ in PLATFORMS]))
        for key, _ in PLATFORMS:
            self.platform_vars[key].set(key in selected)
        self.project_combo.set(PROJECTS[self.project_var.get()]["label"])
        self._sync_count_with_platforms(from_preset=False)
        self._refresh_hints()
        if save_last:
            self._persist_current_config()

    def _persist_current_config(self) -> None:
        self.config_manager.save_last_config(self._collect_config_payload())

    def _generation_mode_key(self, value: str | None = None) -> str:
        value = (value or self.generation_mode_var.get() or "fast").strip()
        if value in GENERATION_MODE_LABELS:
            return value
        return GENERATION_MODE_KEYS.get(value, "fast")

    def _selected_platforms(self) -> list[str]:
        return [key for key, _ in PLATFORMS if self.platform_vars[key].get()]

    def _safe_int(self, value: str, default: int) -> int:
        try:
            return max(1, int(value))
        except ValueError:
            return default

    def _sync_count_with_platforms(self, from_preset: bool) -> None:
        selected = self._selected_platforms()
        if len(selected) == 1:
            current = self.count_var.get().strip()
            if current and current != "3":
                self._last_multi_count = current
            self.count_var.set("3")
        else:
            should_restore = self.count_var.get().strip() == "3" and (
                from_preset or len(selected) > 1
            )
            if should_restore:
                self.count_var.set(self._last_multi_count or "12")

    def _on_platform_toggle(self) -> None:
        if not any(var.get() for var in self.platform_vars.values()):
            self.platform_vars[PLATFORMS[0][0]].set(True)
        self._sync_count_with_platforms(from_preset=False)
        self._refresh_hints()
        self._persist_current_config()

    def _on_generation_mode_change(self) -> None:
        mode = self._generation_mode_key()
        self.generation_mode_var.set(GENERATION_MODE_LABELS.get(mode, GENERATION_MODE_LABELS["fast"]))
        if mode == "fast":
            current = self.workers_var.get().strip()
            if not current or current == "3":
                self.workers_var.set("2")
        elif mode == "one_shot":
            current = self.workers_var.get().strip()
            if not current or current == "1":
                self.workers_var.set("3")
        else:
            self.workers_var.set("1")
        self._refresh_hints()
        self._persist_current_config()

    def _apply_platform_preset(self, preset: str) -> None:
        if preset == "all":
            for key, _ in PLATFORMS:
                self.platform_vars[key].set(True)
        else:
            for key, _ in PLATFORMS:
                self.platform_vars[key].set(key == preset)
        self._sync_count_with_platforms(from_preset=True)
        self._refresh_hints()
        self._persist_current_config()

    def on_main_action(self) -> None:
        on_main_action(self)

    def on_secondary_action(self) -> None:
        on_secondary_action(self)

    def start_new_run(self) -> None:
        start_new_run(self)

    def pause_run(self) -> None:
        self._show_toast("批处理模式下不再支持暂停，请使用停止")

    def resume_run(self) -> None:
        self._show_toast("批处理模式下不再支持继续，请重新开始")

    def clear_current_run(self) -> None:
        clear_current_run(self)

    def stop_run(self) -> None:
        stop_run(self)

    def retry_selected_task(self) -> None:
        retry_selected_task(self)

    def copy_selected_task(self) -> None:
        copy_selected_task(self)

    def export_selected_task(self) -> None:
        export_selected_task(self)

    def delete_selected_task(self) -> None:
        delete_selected_task(self)

    def _launch_batch(self, count: int, workers: int, platforms: list[str], reset_log: bool) -> None:
        launch_batch(self, count, workers, platforms, reset_log)

    def _build_launch_cmd(self, project_key: str, workers: int, count: int, platforms: list[str]) -> list[str]:
        return _build_launch_cmd(self, project_key, workers, count, platforms)

    def _read_output(self) -> None:
        _read_output(self)

    def _poll_queue(self) -> None:
        poll_queue(self)

    def _handle_line(self, line: str) -> None:
        handle_line(self, line)

    def _capture_log_path(self, line: str) -> None:
        capture_log_path(self, line)

    def _extract_global_stage(self, line: str) -> str:
        return extract_global_stage(line)

    def _sync_session_log(self) -> None:
        sync_session_log(self)

    def _discover_log_path(self) -> str:
        return discover_log_path(self)

    def _consume_session_log(self) -> None:
        consume_session_log(self)

    def _handle_process_done(self, code: int) -> None:
        handle_process_done(self, code)

    def _stage_progress_value(self, stage: str) -> float:
        return STAGE_PROGRESS.get(stage, STAGE_PROGRESS.get(self.current_stage, 0.0))

    def _target_progress(self) -> float:
        counts = self.task_manager.counts()
        total = max(counts["total"], self.batch_target)
        if total == 0:
            return 0.0
        if self.task_manager.global_state == GLOBAL_COMPLETED:
            return 1.0
        completed = float(counts["success"] + counts["failed"])
        if counts["total"] == 0:
            completed = float(min(self.batch_saved + self.batch_errors, self.batch_target))
        if completed < total and self._process_is_running():
            completed += self._stage_progress_value(self.current_stage)
        return max(0.0, min(completed / total, 0.995))

    def _animate_progress(self) -> None:
        target = self._target_progress()
        if self.task_manager.global_state == GLOBAL_FAILED and not self._process_is_running():
            target = max(target, self.visual_progress)
        step = 0.01 if target - self.visual_progress > 0.08 else 0.004
        if target > self.visual_progress:
            self.visual_progress = min(target, self.visual_progress + step)
        elif target < self.visual_progress and self.task_manager.global_state in {GLOBAL_IDLE, GLOBAL_COMPLETED}:
            self.visual_progress = target
        self.progress_bar.set(self.visual_progress)
        self.progress_value.configure(text=f"{round(self.visual_progress * 100)}%")
        self.stats_cards["progress"]["value"].configure(text=f"{round(self.visual_progress * 100)}%")
        self.root.after(120, self._animate_progress)

    def _refresh_ui_state(self) -> None:
        state = self.task_manager.global_state
        process_running = self._process_is_running()
        running = state == GLOBAL_RUNNING or process_running
        editable = state in {GLOBAL_IDLE, GLOBAL_COMPLETED, GLOBAL_FAILED}
        if state == GLOBAL_PAUSED:
            editable = False

        self.main_btn.configure(text=GLOBAL_ACTION_LABELS[state])
        self.main_btn.configure(state="disabled" if running else "normal")
        if process_running or state in {GLOBAL_RUNNING, GLOBAL_PAUSED}:
            self.stop_btn.configure(text="停止", state="normal")
        elif state in {GLOBAL_COMPLETED, GLOBAL_FAILED} and (bool(self.task_manager.ordered_tasks()) or self.batch_target > 0):
            self.stop_btn.configure(text="清空重来", state="normal")
        else:
            self.stop_btn.configure(text="清空重来", state="disabled")
        combo_state = "readonly" if editable else "disabled"
        entry_state = "normal" if editable else "disabled"

        self.project_combo.configure(state=combo_state)
        self.count_entry.configure(state=entry_state)
        self.side_count_entry.configure(state=entry_state)
        self.workers_entry.configure(state=entry_state)
        self.mode_combo.configure(state=combo_state)
        for radio in self.project_radios.values():
            radio.configure(state=entry_state)
        for cb in self.platform_checks.values():
            cb.configure(state=entry_state)
        self.platform_all_btn.configure(state="normal" if editable else "disabled")
        for btn in self.single_platform_buttons.values():
            btn.configure(state="normal" if editable else "disabled")
        selected_task = self.task_manager.get_task(self.selected_task_id or "")
        can_retry = bool(selected_task and selected_task.status == TASK_FAILED and not running)
        can_copy = bool(selected_task and selected_task.content)
        can_export = bool(selected_task and selected_task.article_path)
        can_delete = bool(selected_task and not running)
        self.task_retry_btn.configure(state="normal" if can_retry else "disabled")
        self.task_copy_btn.configure(state="normal" if can_copy else "disabled")
        self.task_export_btn.configure(state="normal" if can_export else "disabled")
        self.task_delete_btn.configure(state="normal" if can_delete else "disabled")

    def _refresh_summary(self) -> None:
        counts = self.task_manager.counts()
        progress = self._target_progress()
        total = max(counts["total"], self.batch_target)
        success = counts["success"] if counts["total"] > 0 else self.batch_saved
        failed = counts["failed"] if counts["total"] > 0 else self.batch_errors

        self.stats_cards["success"]["value"].configure(text=str(success))
        self.stats_cards["success"]["hint"].configure(text=f"总任务 {total}")
        self.stats_cards["failed"]["value"].configure(text=str(failed))
        self.stats_cards["failed"]["hint"].configure(text="可单任务重试")
        self.stats_cards["progress"]["hint"].configure(text=self.current_stage)
        self.stats_cards["runtime"]["value"].configure(text=self._runtime_text())
        self.stats_cards["runtime"]["hint"].configure(text=self.current_run_label)
        self.progress_meta.configure(
            text=(
                f"当前阶段：{self.current_stage} · "
                f"已完成 {success} · "
                f"失败 {failed} · "
                f"待处理 {max(total - success - failed, 0)}"
            )
        )

        scores = self.task_manager.score_summary()
        self.result_boxes["excellent"].configure(text=str(scores["excellent"]) if counts["total"] else "--")
        self.result_boxes["qualified"].configure(text=str(scores["qualified"]) if counts["total"] else "--")
        self.result_boxes["rewrite"].configure(text=str(scores["rewrite"]) if counts["total"] else "--")
        self.batch_report.configure(text=self.task_manager.build_batch_report() if counts["total"] else "当前为批处理模式，重点展示整体进度与最终输出结果。")
        self.batch_state_chip.configure(text=GLOBAL_STATE_LABELS[self.task_manager.global_state])

    def _create_task_card(self, task: Task, row: int, accent: str, accent_soft: str, selected: bool) -> dict:
        bar_color = {
            TASK_SUCCESS: "#22C55E",
            TASK_FAILED: "#EF4444",
            TASK_RUNNING: accent,
            TASK_PENDING: "#94A3B8",
        }.get(task.status, "#94A3B8")
        card = self._panel(self.task_list, fg=accent_soft if selected else "#FBFDFF", border=accent if selected else "#E2E8F0", radius=12)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        card.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(card, fg_color=bar_color, width=3, corner_radius=0)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=(12, 12), pady=10)
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        number_label = ctk.CTkLabel(top, font=ctk.CTkFont(family="Segoe UI Semibold", size=13, weight="bold"), text_color="#1E293B")
        number_label.pack(side="left")
        chip = ctk.CTkLabel(top, corner_radius=999, padx=10, pady=3, font=ctk.CTkFont(family="Microsoft YaHei UI", size=10, weight="bold"))
        chip.pack(side="right")
        platform_stage = ctk.CTkLabel(inner, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#64748B")
        platform_stage.pack(anchor="w", pady=(6, 0))
        score_summary = ctk.CTkLabel(inner, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
        score_summary.pack(anchor="w", pady=(3, 0))
        self._bind_click(card, lambda _event, tid=task.id: self.select_task(tid))
        refs = {"card": card, "bar": bar, "number": number_label, "chip": chip, "platform_stage": platform_stage, "score_summary": score_summary}
        self._apply_task_card(refs, task, accent, accent_soft, selected)
        return refs

    def _apply_task_card(self, refs: dict, task: Task, accent: str, accent_soft: str, selected: bool) -> None:
        bar_color = {
            TASK_SUCCESS: "#22C55E",
            TASK_FAILED: "#EF4444",
            TASK_RUNNING: accent,
            TASK_PENDING: "#94A3B8",
        }.get(task.status, "#94A3B8")
        refs["card"].configure(fg_color=accent_soft if selected else "#FBFDFF", border_color=accent if selected else "#E2E8F0")
        refs["bar"].configure(fg_color=bar_color)
        refs["number"].configure(text=f"任务 #{int(task.id):02d}")
        refs["chip"].configure(text=STATUS_LABELS[task.status], fg_color=self._status_bg(task.status), text_color=self._status_fg(task.status))
        platform_label = PLATFORM_LABELS.get(task.platform, task.platform)
        refs["platform_stage"].configure(text=f"{platform_label} · {task.stage}")
        score_text = f"{int(task.score)} 分" if task.score >= 0 else "待评分"
        refs["score_summary"].configure(text=f"{task.summary} · {score_text} · {task.recommendation()}", text_color=task.recommendation_color())

    def _render_tasks(self) -> None:
        items = self.task_manager.ordered_tasks()
        finished = self.task_manager.counts()["success"] + self.task_manager.counts()["failed"]
        denominator = max(len(items), self.batch_target)
        self.task_counter.configure(text=f"{finished} / {denominator}" if denominator > 0 else "0 / 0")

        if not items:
            for refs in self._task_cards.values():
                refs["card"].destroy()
            self._task_cards.clear()
            if getattr(self, "_empty_card", None) is None:
                empty_card = self._panel(self.task_list, fg="#FBFDFF", radius=14)
                empty_card.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
                empty_inner = ctk.CTkFrame(empty_card, fg_color="transparent")
                empty_inner.pack(fill="x", padx=20, pady=24)
                ctk.CTkLabel(empty_inner, text="📋", font=ctk.CTkFont(family="Segoe UI", size=32), text_color="#BCC8D4").pack(anchor="center")
                ctk.CTkLabel(empty_inner, text="暂无任务数据", font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"), text_color="#8CA0B2").pack(anchor="center", pady=(8, 0))
                ctk.CTkLabel(empty_inner, text="启动生成后将在此展示每篇文章的独立任务卡片，可单独查看详情、复制内容和导出文件。", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#A8B9C8", wraplength=360, justify="center").pack(anchor="center", pady=(6, 0))
                self._empty_card = empty_card
            return

        if getattr(self, "_empty_card", None) is not None:
            self._empty_card.destroy()
            self._empty_card = None

        accent = self._cfg()["accent"]
        accent_soft = self._cfg()["accent_soft"]
        current_ids = {task.id for task in items}

        for task_id in list(self._task_cards.keys()):
            if task_id not in current_ids:
                self._task_cards[task_id]["card"].destroy()
                del self._task_cards[task_id]

        for row, task in enumerate(items):
            selected = task.id == self.selected_task_id
            if task.id in self._task_cards:
                refs = self._task_cards[task.id]
                refs["card"].grid(row=row, column=0, sticky="ew", pady=(0, 6))
                self._apply_task_card(refs, task, accent, accent_soft, selected)
            else:
                refs = self._create_task_card(task, row, accent, accent_soft, selected)
                self._task_cards[task.id] = refs

    def select_task(self, task_id: str) -> None:
        self.selected_task_id = task_id
        self._refresh_ui_state()
        self._render_tasks()
        self._render_detail()

    def _render_detail(self) -> None:
        task = self.task_manager.get_task(self.selected_task_id or "")
        if not task:
            self.detail_title_label.configure(text="任务详情")
            self.detail_subtitle.configure(text="选择左侧任务卡片查看完整信息")
            self.detail_meta.configure(text="")
            for value in self.detail_metric_labels.values():
                value.configure(text="--", text_color="#94A3B8")
            self._set_textbox(self.preview_box, "点击任务卡片后，此处将展示文章正文内容。")
            self._set_textbox(self.timeline_box, "任务时间线将显示生成流程中各阶段的耗时与状态。")
            self._set_textbox(self.calls_box, "LLM 调用记录将列出每次模型请求的模型、Token 消耗与状态。")
            return

        platform_label = PLATFORM_LABELS.get(task.platform, task.platform)
        self.detail_title_label.configure(text=f"任务 #{int(task.id):02d} · {platform_label}")
        self.detail_subtitle.configure(text=f"状态：{STATUS_LABELS[task.status]} · 阶段：{task.stage}")
        meta_lines = [
            f"基础关键词：{task.base_keyword or '待解析'}",
            f"长尾关键词：{task.keyword or '待生成'}",
            f"标题结果：{task.title or '待生成'}",
            f"输出文件：{task.article_path or '待生成'}",
            f"重试次数：{task.retries}",
        ]
        if task.failed_stage:
            meta_lines.append(f"失败阶段：{self.task_manager.failure_stage_label(task.failed_stage)}")
        if task.failure_reason:
            meta_lines.append(f"失败原因：{task.failure_reason}")
        if task.error:
            meta_lines.append(f"异常信息：{task.error}")
        self.detail_meta.configure(text="\n".join(meta_lines))
        self.detail_metric_labels["score"].configure(text=f"{int(task.score)} 分" if task.score >= 0 else "--", text_color="#133248")
        total_tokens = task.prompt_tokens + task.completion_tokens
        self.detail_metric_labels["tokens"].configure(text=str(total_tokens) if total_tokens else "--", text_color="#133248")
        self.detail_metric_labels["result"].configure(text=task.recommendation(), text_color=task.recommendation_color())
        preview = task.content or "当前任务还没有可预览内容。"
        timeline = "\n".join(task.events[-16:]) or "暂无结构化任务流。"
        calls = self._format_calls(task.llm_calls)
        new_sig = (task.id, task.status, task.stage, preview, timeline, calls)
        if getattr(self, "_detail_sig", None) != new_sig:
            self._detail_sig = new_sig
            self._set_textbox(self.preview_box, preview)
            self._set_textbox(self.timeline_box, timeline)
            self._set_textbox(self.calls_box, calls)
        self._refresh_ui_state()

    def _schedule_task_refresh(self) -> None:
        """Coalesce rapid _render_tasks / _render_detail calls into a single update."""
        if self._ui_refresh_scheduled:
            return
        self._ui_refresh_scheduled = True
        self.root.after(250, self._do_task_refresh)

    def _do_task_refresh(self) -> None:
        self._ui_refresh_scheduled = False
        self._render_tasks()
        self._render_detail()

    def _format_calls(self, calls: list[dict]) -> str:
        if not calls:
            return "暂无 LLM 调用记录。"
        lines = []
        for index, call in enumerate(calls, start=1):
            lines.append(
                f"{index}. 层级 {call.get('tier', 'unknown')} | 模型 {call.get('model', 'unknown')} | "
                f"尝试 {call.get('attempt') or 1}/{call.get('max_attempts') or 1} | "
                f"输入 {call.get('prompt_tokens') or 0} | 输出 {call.get('completion_tokens') or 0} | "
                f"状态 {call.get('status') or 'ok'}"
            )
            if call.get("error"):
                lines.append(f"   错误：{call['error']}")
        return "\n".join(lines)

    def _set_textbox(self, textbox: ctk.CTkTextbox, text: str) -> None:
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")

    def _status_bg(self, status: str) -> str:
        return {
            TASK_SUCCESS: "#EAF7EF",
            TASK_FAILED: "#FFF1F1",
            TASK_RUNNING: self._cfg()["accent_soft"],
            TASK_PENDING: "#F2F7FB",
        }[status]

    def _status_fg(self, status: str) -> str:
        return {
            TASK_SUCCESS: "#15803D",
            TASK_FAILED: "#C24141",
            TASK_RUNNING: self._cfg()["accent_deep"],
            TASK_PENDING: "#617A91",
        }[status]

    def _runtime_text(self) -> str:
        if not self.start_time:
            return "00:00"
        seconds = int((datetime.now() - self.start_time).total_seconds())
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _tick_runtime(self) -> None:
        self._refresh_summary()
        self.root.after(1000, self._tick_runtime)

    def _show_toast(self, text: str) -> None:
        if self._toast_after_id:
            self.root.after_cancel(self._toast_after_id)
        self.toast_label.configure(text=text, fg_color=self._cfg()["accent_soft"], text_color=self._cfg()["accent_deep"])
        self._toast_after_id = self.root.after(2600, lambda: self.toast_label.configure(text="", fg_color="transparent"))

    def _bind_click(self, widget, callback) -> None:
        bind_click(widget, callback)

    def _show_done_popup(self) -> None:
        counts = self.task_manager.counts()
        success = counts["success"]
        failed = counts["failed"]
        total = max(counts["total"], self.batch_target)
        ok = failed == 0

        popup = ctk.CTkToplevel(self.root)
        popup.title("批处理完成")
        popup.geometry("380x240")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.grab_set()
        popup.configure(fg_color="#FFFFFF")
        self.root.eval(f'tk::PlaceWindow {popup} center')

        ctk.CTkLabel(popup, text="完成" if ok else "完成", font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"), text_color="#1E293B").pack(pady=(24, 4))
        ctk.CTkLabel(popup, text=f"成功 {success} · 失败 {failed} · 共 {total} 篇", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#64748B").pack()

        output_root = _project_dir(self.project_var.get()) / "output"
        output_root.mkdir(exist_ok=True)

        def _open_and_close():
            self.open_latest_output_folder()
            popup.destroy()

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(pady=(20, 0))
        ctk.CTkButton(btn_frame, text="打开输出目录", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
                       fg_color=self._cfg()["accent"], hover_color=self._cfg()["accent_deep"], text_color="#FFFFFF",
                       corner_radius=10, width=140, height=36, command=_open_and_close).pack(side="left", padx=(0, 12))
        ctk.CTkButton(btn_frame, text="关闭", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
                       fg_color="#E2E8F0", hover_color="#CBD5E1", text_color="#475569",
                       corner_radius=10, width=100, height=36, command=popup.destroy).pack(side="left")

    def open_latest_output_folder(self) -> None:
        output_root = _project_dir(self.project_var.get()) / "output"
        output_root.mkdir(exist_ok=True)
        subdirs = [item for item in output_root.iterdir() if item.is_dir()]
        os.startfile(max(subdirs, key=lambda item: item.stat().st_mtime) if subdirs else output_root)

    def _find_latest_txt_file(self) -> Path | None:
        output_root = _project_dir(self.project_var.get()) / "output"
        if not output_root.exists():
            return None
        files = [item for item in output_root.rglob("*.txt") if item.is_file()]
        return max(files, key=lambda item: item.stat().st_mtime) if files else None

    def open_latest_txt_folder(self) -> None:
        latest = self._find_latest_txt_file()
        if latest:
            os.startfile(latest.parent)
        else:
            self._show_toast("暂未找到 TXT 文件")

    def open_latest_txt_file(self) -> None:
        latest = self._find_latest_txt_file()
        if latest:
            os.startfile(latest)
        else:
            self._show_toast("暂未找到 TXT 文件")

    def _cancel_pause_timeout(self) -> None:
        if self._pause_timeout_id:
            self.root.after_cancel(self._pause_timeout_id)
            self._pause_timeout_id = None

    def _process_is_running(self) -> bool:
        return process_is_running(self)

    def _terminate_process_tree(self) -> None:
        terminate_process_tree(self)

    def _pause_timeout_kill(self) -> None:
        self._pause_timeout_id = None
        self._terminate_process_tree()
        self._show_toast("暂停超时（120 秒），已强制终止，可继续剩余任务")

    def _clear_pause_file(self) -> None:
        if self._pause_file_path:
            try:
                Path(self._pause_file_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _on_close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(APP_TITLE, "当前任务仍在运行，关闭会终止任务，确定继续吗？"):
                return
            self._cancel_pause_timeout()
            self._terminate_process_tree()
        self._clear_pause_file()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
