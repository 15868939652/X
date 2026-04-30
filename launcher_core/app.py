from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from launcher_core.config_manager import ConfigManager
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
from launcher_core.task_manager import TaskManager

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
PROJECTS = {
    "yiwu_yicheng": {
        "label": "义乌义城医院",
        "accent": "#2F74B5",
        "accent_deep": "#1E558A",
        "accent_soft": "#EEF5FC",
    },
    "yiwu_weichuang": {
        "label": "义乌微创医院",
        "accent": "#D986AE",
        "accent_deep": "#B86490",
        "accent_soft": "#FDF1F7",
    },
}
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
        self.current_plan_path = ""
        self.selected_task_id: str | None = None
        self._flask_thread: threading.Thread | None = None
        self._toast_after_id = None
        self._pause_file_path = ""
        self._pause_timeout_id = None
        self._last_multi_count = "12"

        self.project_var = tk.StringVar(value="yiwu_yicheng")
        self.count_var = tk.StringVar(value="12")
        self.workers_var = tk.StringVar(value="2")
        self.generation_mode_var = tk.StringVar(value=GENERATION_MODE_LABELS["fast"])
        self.platform_vars = {key: tk.BooleanVar(value=True) for key, _ in PLATFORMS}
        self.template_var = tk.StringVar(value="")

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
        return ctk.CTkFrame(parent, fg_color=fg, corner_radius=radius, border_width=1, border_color=border)

    def _title(self, parent, text: str, size: int = 13):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=size, weight="bold"),
            text_color="#133248",
        )

    def _subtext(self, parent, text: str, wrap: int = 270):
        return ctk.CTkLabel(
            parent,
            text=text,
            justify="left",
            wraplength=wrap,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#6B8195",
        )

    def _build_topbar(self) -> None:
        top = ctk.CTkFrame(self.root, fg_color="#FFFFFF", corner_radius=0, height=68, border_width=1, border_color="#D8E3EE")
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)
        top.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=(18, 14), pady=12)
        self.brand_badge = ctk.CTkLabel(
            brand,
            text="X",
            width=40,
            height=40,
            corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=20, weight="bold"),
            text_color="#FFFFFF",
        )
        self.brand_badge.pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            brand_text,
            text=APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=20, weight="bold"),
            text_color="#133248",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text=APP_SUBTITLE,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#617A91",
        ).pack(anchor="w")

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e", padx=(0, 18), pady=12)
        ctk.CTkLabel(controls, text="项目", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"), text_color="#617A91").grid(row=0, column=0, padx=(0, 8))
        self.project_combo = ctk.CTkComboBox(
            controls,
            width=160,
            height=38,
            values=[cfg["label"] for cfg in PROJECTS.values()],
            state="readonly",
            command=self._on_combo_project_change,
        )
        self.project_combo.grid(row=0, column=1, padx=(0, 12))

        self.main_btn = ctk.CTkButton(
            controls,
            text=GLOBAL_ACTION_LABELS[GLOBAL_IDLE],
            width=128,
            height=40,
            corner_radius=14,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=14, weight="bold"),
            command=self.on_main_action,
        )
        self.main_btn.grid(row=0, column=2, padx=(0, 10))
        self.stop_btn = ctk.CTkButton(
            controls,
            text="停止",
            width=96,
            height=40,
            corner_radius=14,
            command=self.on_secondary_action,
        )
        self.stop_btn.grid(row=0, column=3)

    def _build_sidebar(self) -> None:
        shell = ctk.CTkFrame(self.root, fg_color="#F7FAFD", width=304, corner_radius=0)
        shell.grid(row=1, column=0, sticky="nsew")
        shell.grid_propagate(False)
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        sidebar = ctk.CTkScrollableFrame(shell, width=284, fg_color="transparent")
        sidebar.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar = sidebar

        intro = self._panel(sidebar)
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        intro_inner = ctk.CTkFrame(intro, fg_color="transparent")
        intro_inner.pack(fill="x", padx=16, pady=16)
        self._title(intro_inner, "内容生产工作台").pack(anchor="w")
        self._subtext(
            intro_inner,
            "面向医疗内容批量生成、过程质控与结果交付，支持任务追踪、模板复用、失败重试和批次复盘。",
            wrap=258,
        ).pack(anchor="w", pady=(8, 0))

        project_card = self._panel(sidebar)
        project_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        inner = ctk.CTkFrame(project_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self._title(inner, "1. 项目选择").pack(anchor="w")
        self.project_radios = {}
        for index, (key, cfg) in enumerate(PROJECTS.items()):
            radio = ctk.CTkRadioButton(inner, text=cfg["label"], variable=self.project_var, value=key, command=self.switch_project)
            radio.pack(anchor="w", pady=(10 if index == 0 else 8, 0))
            self.project_radios[key] = radio

        platform_card = self._panel(sidebar)
        platform_card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        inner = ctk.CTkFrame(platform_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
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
        settings_card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        inner = ctk.CTkFrame(settings_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
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

        template_card = self._panel(sidebar)
        template_card.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        inner = ctk.CTkFrame(template_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self._title(inner, "4. 配置模板").pack(anchor="w")
        self.template_combo = ctk.CTkComboBox(inner, width=240, height=36, values=[], variable=self.template_var, state="readonly")
        self.template_combo.pack(anchor="w", pady=(10, 0))
        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", pady=(10, 0))
        actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="t")
        self.template_save_btn = ctk.CTkButton(actions, text="保存", height=34, corner_radius=12, command=self.save_template)
        self.template_save_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.template_load_btn = ctk.CTkButton(actions, text="加载", height=34, corner_radius=12, command=self.load_template)
        self.template_load_btn.grid(row=0, column=1, sticky="ew", padx=4)
        self.template_delete_btn = ctk.CTkButton(actions, text="删除", height=34, corner_radius=12, command=self.delete_template)
        self.template_delete_btn.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        tool_card = self._panel(sidebar)
        tool_card.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        inner = ctk.CTkFrame(tool_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        self._title(inner, "快捷入口").pack(anchor="w")
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x", pady=(10, 0))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="tool")
        self.btn_latest_dir = ctk.CTkButton(grid, text="最新批次", height=34, corner_radius=12, command=self.open_latest_output_folder)
        self.btn_latest_dir.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.btn_txt_dir = ctk.CTkButton(grid, text="TXT目录", height=34, corner_radius=12, command=self.open_latest_txt_folder)
        self.btn_txt_dir.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        self.btn_txt_file = ctk.CTkButton(grid, text="TXT文件", height=34, corner_radius=12, command=self.open_latest_txt_file)
        self.btn_txt_file.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.btn_review = ctk.CTkButton(grid, text="审核台", height=34, corner_radius=12, command=self.start_review)
        self.btn_review.grid(row=1, column=1, sticky="ew", padx=(4, 0))

    def _entry_row(self, parent, label: str, variable: tk.StringVar):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"), text_color="#617A91").pack(side="left")
        entry = ctk.CTkEntry(row, width=96, height=36, textvariable=variable, justify="center", corner_radius=12)
        entry.pack(side="right")
        return entry

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
        row.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        for idx in range(4):
            row.grid_columnconfigure(idx, weight=1, uniform="stats")

        self.stats_cards = {}
        stats = [
            ("success", "已完成"),
            ("failed", "失败数"),
            ("progress", "进度"),
            ("runtime", "运行时间"),
        ]
        for idx, (key, title) in enumerate(stats):
            card = self._panel(row)
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0 if idx == 3 else 6))
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=16, pady=16)
            ctk.CTkLabel(inner, text=title, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91").pack(anchor="w")
            value = ctk.CTkLabel(inner, text="0", font=ctk.CTkFont(family="Segoe UI Semibold", size=28, weight="bold"), text_color="#133248")
            value.pack(anchor="w", pady=(8, 0))
            hint = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#8CA0B2")
            hint.pack(anchor="w", pady=(4, 0))
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
        footer = ctk.CTkFrame(self.root, fg_color="transparent")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_status = ctk.CTkLabel(footer, text="等待启动", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color="#617A91")
        self.footer_status.grid(row=0, column=0, sticky="w")
        self.toast_label = ctk.CTkLabel(footer, text="", corner_radius=999, padx=14, pady=6, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"))
        self.toast_label.grid(row=0, column=1, sticky="e")

    def _load_initial_config(self) -> None:
        payload = self.config_manager.load_last_config()
        if payload:
            self._apply_config_payload(payload, save_last=False)
        self.project_combo.set(PROJECTS[self.project_var.get()]["label"])
        self._reload_template_combo()
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
        cfg = self._cfg()
        accent = cfg["accent"]
        accent_deep = cfg["accent_deep"]
        accent_soft = cfg["accent_soft"]
        self.brand_badge.configure(fg_color=accent)
        self.main_btn.configure(fg_color=accent, hover_color=accent_deep, text_color="#FFFFFF")
        for btn in [
            self.stop_btn,
            self.platform_all_btn,
            self.template_save_btn,
            self.template_load_btn,
            self.template_delete_btn,
            self.btn_latest_dir,
            self.btn_txt_dir,
            self.btn_txt_file,
            self.btn_review,
            self.task_retry_btn,
            self.task_copy_btn,
            self.task_export_btn,
            self.task_delete_btn,
            *self.single_platform_buttons.values(),
        ]:
            btn.configure(fg_color=accent_soft, hover_color=accent_soft, text_color=accent_deep, border_width=1, border_color=accent)
        self.progress_bar.configure(progress_color=accent)
        self.batch_state_chip.configure(fg_color=accent_soft, text_color=accent_deep)

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

    def _reload_template_combo(self) -> None:
        templates = self.config_manager.list_templates()
        values = [item["name"] for item in templates]
        self.template_combo.configure(values=values or [""])
        if values:
            current = self.template_var.get()
            self.template_combo.set(current if current in values else values[0])
        else:
            self.template_combo.set("")

    def save_template(self) -> None:
        dialog = ctk.CTkInputDialog(text="输入模板名称", title="保存模板")
        name = dialog.get_input() if dialog else None
        if not name:
            return
        try:
            clean_name = self.config_manager.save_template(name, self._collect_config_payload())
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.template_var.set(clean_name)
        self._reload_template_combo()
        self._show_toast(f"模板已保存：{clean_name}")

    def load_template(self) -> None:
        item = self.config_manager.load_template(self.template_var.get())
        if not item:
            self._show_toast("未找到该模板")
            return
        self._apply_config_payload(item)
        self.switch_project()
        self._show_toast(f"已加载模板：{item['name']}")

    def delete_template(self) -> None:
        name = self.template_var.get()
        if not name:
            return
        if not messagebox.askyesno(APP_TITLE, f"确定删除模板“{name}”吗？"):
            return
        if self.config_manager.delete_template(name):
            self.template_var.set("")
            self._reload_template_combo()
            self._show_toast(f"已删除模板：{name}")

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
        if self.task_manager.global_state not in {GLOBAL_RUNNING, GLOBAL_PAUSED}:
            self.start_new_run()

    def on_secondary_action(self) -> None:
        if self._process_is_running() or self.task_manager.global_state in {GLOBAL_RUNNING, GLOBAL_PAUSED}:
            self.stop_run()
            return
        if self.task_manager.ordered_tasks() or self.batch_target > 0:
            self.clear_current_run()

    def start_new_run(self) -> None:
        if self.process and self.process.poll() is None:
            return
        platforms = self._selected_platforms()
        if not platforms:
            self._show_toast("请至少选择一个平台")
            return

        count = self._safe_int(self.count_var.get(), 12)
        workers = self._safe_int(self.workers_var.get(), 3)
        project_key = self.project_var.get()
        _ensure_runtime_project(project_key)
        self.task_manager.reset()
        self.task_manager.global_state = GLOBAL_RUNNING
        self.selected_task_id = None
        self.batch_target = count
        self.batch_saved = 0
        self.batch_errors = 0
        self._persist_current_config()
        self._launch_batch(count, workers, platforms, reset_log=True)

    def pause_run(self) -> None:
        self._show_toast("批处理模式下不再支持暂停，请使用停止")

    def resume_run(self) -> None:
        self._show_toast("批处理模式下不再支持继续，请重新开始")

    def clear_current_run(self) -> None:
        self._cancel_pause_timeout()
        self._clear_pause_file()
        self._terminate_process_tree()
        if self.current_plan_path:
            try:
                Path(self.current_plan_path).unlink(missing_ok=True)
            except Exception:
                pass
        self.task_manager.reset()
        self.process = None
        self.reader_thread = None
        self.selected_task_id = None
        self.start_time = None
        self.current_plan_path = ""
        self.session_log_path = ""
        self.session_log_offset = 0
        self.current_stage = "等待启动"
        self.current_run_label = "待机中"
        self.visual_progress = 0.0
        self.batch_target = 0
        self.batch_saved = 0
        self.batch_errors = 0
        self.footer_status.configure(text="已清空当前批次，可重新开始")
        self._refresh_summary()
        self._refresh_ui_state()
        self._render_tasks()
        self._render_detail()
        self._show_toast("已清空当前批次")

    def stop_run(self) -> None:
        self._cancel_pause_timeout()
        self._clear_pause_file()
        self._terminate_process_tree()
        self.task_manager.global_state = GLOBAL_FAILED
        self.batch_errors = max(self.batch_errors, 1)
        self.footer_status.configure(text="当前批次已停止")
        self._show_toast("已停止当前批次")
        self._refresh_ui_state()

    def retry_selected_task(self) -> None:
        self._show_toast("批处理模式下已关闭单任务重试")

    def copy_selected_task(self) -> None:
        if not self.selected_task_id:
            return
        text = self.task_manager.copy_text(self.selected_task_id)
        if not text:
            self._show_toast("当前任务还没有可复制的内容")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._show_toast("已复制当前任务内容")

    def export_selected_task(self) -> None:
        task = self.task_manager.get_task(self.selected_task_id or "")
        if not task or not task.article_path:
            self._show_toast("当前任务还没有输出文件")
            return
        target = filedialog.asksaveasfilename(
            title="导出任务文件",
            defaultextension=".txt",
            initialfile=Path(task.article_path).name,
            filetypes=[("Text", "*.txt")],
        )
        if not target:
            return
        Path(target).write_text(_read_text(task.article_path), encoding="utf-8")
        self._show_toast("导出完成")

    def delete_selected_task(self) -> None:
        self._show_toast("批处理模式下已关闭单任务删除")

    def _launch_batch(self, count: int, workers: int, platforms: list[str], reset_log: bool) -> None:
        project_key = self.project_var.get()
        project_dir = _project_dir(project_key)
        self.start_time = datetime.now()
        self.current_stage = "关键词扩展"
        self.current_run_label = f"{PROJECTS[project_key]['label']} · {count} 篇"
        self.visual_progress = 0.02
        if reset_log:
            self.session_log_path = ""
            self.session_log_offset = 0
        self._refresh_summary()
        self._refresh_ui_state()
        self.footer_status.configure(text=f"任务启动中 · {self.current_run_label}")

        cmd = self._build_launch_cmd(project_key, workers, count, platforms)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
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
            self.process = None
            self.task_manager.global_state = GLOBAL_FAILED
            messagebox.showerror(APP_TITLE, f"启动失败：{exc}")
            self._refresh_ui_state()
            return

        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()
        self._show_toast("任务已开始运行")

    def _build_launch_cmd(self, project_key: str, workers: int, count: int, platforms: list[str]) -> list[str]:
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
            self._generation_mode_key(),
        ]
        return cmd

    def _read_output(self) -> None:
        try:
            if self.process and self.process.stdout:
                for line in self.process.stdout:
                    self.queue.put(("line", line.rstrip("\r\n")))
        finally:
            if self.process:
                self.queue.put(("done", self.process.wait()))

    def _poll_queue(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._handle_line(payload)
            elif kind == "done":
                self._handle_process_done(payload)
        self.root.after(100, self._poll_queue)

    def _handle_line(self, line: str) -> None:
        if not line.strip():
            return
        self._capture_log_path(line)
        self.current_stage = self._extract_global_stage(line) or self.current_stage
        self.task_manager.apply_runtime_line(line)
        if "[SAVE]" in line or "已保存" in line:
            self.batch_saved = min(self.batch_target, self.batch_saved + 1)
        if "[ERR]" in line or "失败" in line:
            self.batch_errors += 1
        self._refresh_summary()
        self._render_tasks()
        self._render_detail()

    def _capture_log_path(self, line: str) -> None:
        match = re.search(r"(logs[\\/]+generation_\d{8}_\d{6}\.jsonl)", line)
        if not match or self.session_log_path:
            return
        self.session_log_path = str(_project_dir(self.project_var.get()) / match.group(1).replace("\\", os.sep).replace("/", os.sep))
        self.session_log_offset = 0

    def _extract_global_stage(self, line: str) -> str:
        for key, value in STAGE_MAPPING.items():
            if key in line:
                return value
        return ""

    def _sync_session_log(self) -> None:
        if self.process or self.session_log_path:
            if not self.session_log_path:
                self.session_log_path = self._discover_log_path()
            if self.session_log_path and os.path.exists(self.session_log_path):
                self._consume_session_log()
        self.root.after(700, self._sync_session_log)

    def _discover_log_path(self) -> str:
        project_logs = _project_dir(self.project_var.get()) / "logs"
        if not project_logs.exists() or not self.start_time:
            return ""
        candidates = sorted(project_logs.glob("generation_*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
        threshold = self.start_time.timestamp() - 3
        for item in candidates:
            if item.stat().st_mtime >= threshold:
                return str(item)
        return str(candidates[0]) if candidates else ""

    def _consume_session_log(self) -> None:
        try:
            with open(self.session_log_path, "r", encoding="utf-8") as f:
                f.seek(self.session_log_offset)
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    self.task_manager.apply_record(record, str(_project_dir(self.project_var.get())))
                self.session_log_offset = f.tell()
        except OSError:
            return
        self._refresh_summary()
        self._render_tasks()
        self._render_detail()

    def _handle_process_done(self, code: int) -> None:
        self._cancel_pause_timeout()
        self._clear_pause_file()
        self._consume_session_log()
        self.process = None
        if code == 0:
            self.task_manager.global_state = GLOBAL_COMPLETED
            self.visual_progress = 1.0
            self.batch_saved = max(self.batch_saved, self.batch_target)
        else:
            self.task_manager.global_state = GLOBAL_FAILED
        self.footer_status.configure(text="任务完成" if code == 0 else f"任务结束 · 退出码 {code}")
        self._refresh_summary()
        self._refresh_ui_state()
        self._render_tasks()
        self._render_detail()
        self._show_toast("本轮任务已结束")

    def _stage_progress_value(self, stage: str) -> float:
        return STAGE_PROGRESS.get(stage, STAGE_PROGRESS.get(self.current_stage, 0.0))

    def _target_progress(self) -> float:
        counts = self.task_manager.counts()
        total = counts["total"]
        if total == 0 and self.batch_target > 0:
            completed = min(self.batch_saved + self.batch_errors, self.batch_target)
            progress = float(completed)
            if completed < self.batch_target and self._process_is_running():
                progress += self._stage_progress_value(self.current_stage)
            if self.task_manager.global_state == GLOBAL_COMPLETED:
                return 1.0
            return max(0.0, min(progress / self.batch_target, 0.995))
        if total == 0:
            return 0.0
        completed = counts["success"] + counts["failed"]
        progress = float(completed)
        for task in self.task_manager.ordered_tasks():
            if task.status == TASK_RUNNING:
                progress += self._stage_progress_value(task.stage)
        target = progress / total
        if self.task_manager.global_state == GLOBAL_COMPLETED:
            return 1.0
        return max(0.0, min(target, 0.995))

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
        self.template_combo.configure(state=combo_state)
        self.mode_combo.configure(state=combo_state)
        for radio in self.project_radios.values():
            radio.configure(state=entry_state)
        for cb in self.platform_checks.values():
            cb.configure(state=entry_state)
        self.platform_all_btn.configure(state="normal" if editable else "disabled")
        for btn in self.single_platform_buttons.values():
            btn.configure(state="normal" if editable else "disabled")
        for btn in (self.template_save_btn, self.template_load_btn, self.template_delete_btn):
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
        total = counts["total"] or self.batch_target
        success = counts["success"] or self.batch_saved
        failed = counts["failed"] or self.batch_errors

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

    def _render_tasks(self) -> None:
        for child in self.task_list.winfo_children():
            child.destroy()

        items = self.task_manager.ordered_tasks()
        finished = self.task_manager.counts()["success"] + self.task_manager.counts()["failed"]
        if not items and self.batch_target > 0:
            self.task_counter.configure(text=f"{self.batch_saved + self.batch_errors} / {self.batch_target}")
        else:
            self.task_counter.configure(text=f"{finished} / {len(items)}")
        if not items:
            ctk.CTkLabel(
                self.task_list,
                text="当前已回退为批处理模式，不再展示每篇文章的独立任务卡片。",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
                text_color="#8CA0B2",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return

        accent = self._cfg()["accent"]
        accent_soft = self._cfg()["accent_soft"]
        for row, task in enumerate(items):
            selected = task.id == self.selected_task_id
            card = self._panel(self.task_list, fg=accent_soft if selected else "#FBFDFF", border=accent if selected else "#D8E3EE", radius=14)
            card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            card.grid_columnconfigure(0, weight=1)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=12)
            top = ctk.CTkFrame(inner, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=f"任务 #{int(task.id):02d}", font=ctk.CTkFont(family="Segoe UI Semibold", size=14, weight="bold"), text_color="#133248").pack(side="left")
            chip = ctk.CTkLabel(top, text=STATUS_LABELS[task.status], corner_radius=999, padx=10, pady=4, font=ctk.CTkFont(family="Microsoft YaHei UI", size=10, weight="bold"))
            chip.pack(side="right")
            chip.configure(fg_color=self._status_bg(task.status), text_color=self._status_fg(task.status))

            platform_label = PLATFORM_LABELS.get(task.platform, task.platform)
            ctk.CTkLabel(inner, text=f"{platform_label} · {task.stage}", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color="#617A91").pack(anchor="w", pady=(8, 0))
            score_label = f"{int(task.score)} 分" if task.score >= 0 else "待评分"
            ctk.CTkLabel(inner, text=f"{task.summary} · {score_label} · {task.recommendation()}", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color=task.recommendation_color()).pack(anchor="w", pady=(4, 0))
            self._bind_click(card, lambda _event, task_id=task.id: self.select_task(task_id))

    def select_task(self, task_id: str) -> None:
        self.selected_task_id = task_id
        self._refresh_ui_state()
        self._render_tasks()
        self._render_detail()

    def _render_detail(self) -> None:
        task = self.task_manager.get_task(self.selected_task_id or "")
        self._set_textbox(self.preview_box, "")
        self._set_textbox(self.timeline_box, "")
        self._set_textbox(self.calls_box, "")
        if not task:
            self.detail_title_label.configure(text="请选择任务查看详情")
            self.detail_subtitle.configure(text="")
            self.detail_meta.configure(text="")
            for value in self.detail_metric_labels.values():
                value.configure(text="--", text_color="#133248")
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
        self._set_textbox(self.preview_box, task.content or "当前任务还没有可预览内容。")
        self._set_textbox(self.timeline_box, "\n".join(task.events[-16:]) or "暂无结构化任务流。")
        self._set_textbox(self.calls_box, self._format_calls(task.llm_calls))
        self._refresh_ui_state()

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
        widget.bind("<Button-1>", callback)
        for child in widget.winfo_children():
            self._bind_click(child, callback)

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

    def start_review(self) -> None:
        if self._flask_thread and self._flask_thread.is_alive():
            webbrowser.open("http://127.0.0.1:5050")
            return

        project_dir = str(_project_dir(self.project_var.get()))
        shared_dir = str(_runtime_root() / "shared")

        def run_flask():
            if project_dir not in sys.path:
                sys.path.insert(0, project_dir)
            if shared_dir not in sys.path:
                sys.path.append(shared_dir)
            import bootstrap_shared  # noqa: F401
            from review_ui import app as flask_app

            flask_app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)

        self._flask_thread = threading.Thread(target=run_flask, daemon=True)
        self._flask_thread.start()
        self.root.after(1200, lambda: webbrowser.open("http://127.0.0.1:5050"))
        self._show_toast("审核台已在浏览器中打开")

    def _cancel_pause_timeout(self) -> None:
        if self._pause_timeout_id:
            self.root.after_cancel(self._pause_timeout_id)
            self._pause_timeout_id = None

    def _process_is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def _terminate_process_tree(self) -> None:
        if not self.process:
            return
        if self.process.poll() is not None:
            self.process = None
            return
        pid = self.process.pid
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
                self.process.terminate()
            except Exception:
                pass

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
