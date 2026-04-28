import os
import re
import sys
import queue
import threading
import subprocess
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

APP_TITLE = "多平台文章生成器"
APP_SUBTITLE = "多平台优化与内容质控中心"

if getattr(sys, "frozen", False):
    ROOT_DIR = sys._MEIPASS
else:
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECTS_DIR = os.path.join(ROOT_DIR, "projects")

HOSPITALS = {
    "yiwu_yicheng": {
        "label": "义乌义城医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_yicheng"),
        "accent": "#2F76B7",
        "accent_deep": "#1E578C",
        "accent_soft": "#EEF5FC",
        "accent_line": "#C9DDF0",
        "glow": "#79AEDD",
    },
    "yiwu_weichuang": {
        "label": "义乌微创医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_weichuang"),
        "accent": "#D86C9A",
        "accent_deep": "#B95481",
        "accent_soft": "#FFF3F8",
        "accent_line": "#F4C7DA",
        "glow": "#F2A8C7",
    },
}

PLATFORMS = {
    "all": "全平台",
    "zhihu": "知乎",
    "sohu": "搜狐",
    "baijiahao": "百家号",
    "toutiao": "头条",
}

STAGE_STEPS = ["长尾扩展", "首稿生成", "去AI化", "评分重写", "保存完成"]
STAGE_MILESTONES = [0.10, 0.52, 0.74, 0.90, 1.00]
BASE_STAGE_SECONDS = [10, 34, 18, 20, 10]

PALETTE = {
    "page": "#F4F8FB",
    "sidebar": "#11314A",
    "sidebar_card": "#183B56",
    "surface": "#FFFFFF",
    "surface_alt": "#EDF4F9",
    "border": "#D5E1EB",
    "text": "#12324A",
    "muted": "#4D6B82",
    "soft": "#7F97AB",
    "success": "#15803D",
    "warning": "#B45309",
    "danger": "#B91C1C",
    "log_bg": "#F7FBFE",
    "log_text": "#355066",
}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class LauncherApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title(APP_TITLE)
        self.root.geometry("1360x860")
        self.root.minsize(1120, 720)
        self.root.configure(fg_color=PALETTE["page"])

        self.process = None
        self.process_mode = None
        self.current_hospital = "yiwu_yicheng"
        self.reader_thread = None
        self.queue = queue.Queue()
        self.start_time = None
        self.saved_count = 0
        self.error_count = 0
        self.progress_target = 12
        self._remain_target = 0
        self.run_output_baseline_ts = 0.0
        self.current_stage = "准备就绪"
        self.current_run_label = "全量模式"
        self.stage_index = -1
        self.visual_progress = 0.0
        self.stage_started_at = None
        self._selected_mode = "all"
        self._toast_after_id = None
        self._flask_thread = None
        self._flask_port = 5050

        self._build_ui()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll_queue)
        self.root.after(120, self._animate_progress)

    def _cfg(self):
        return HOSPITALS[self.current_hospital]

    def _project_dir(self):
        return self._cfg()["dir"]

    def _config_path(self):
        return os.path.join(self._project_dir(), "config.py")

    def _main_py(self):
        return os.path.join(self._project_dir(), "main.py")

    def _review_py(self):
        return os.path.join(self._project_dir(), "review_ui.py")

    def _logs_dir(self):
        return os.path.join(self._project_dir(), "logs")

    def _output_dir(self):
        return os.path.join(self._project_dir(), "output")

    def _read_config_int(self, key: str, default: int) -> int:
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                match = re.search(rf"^{key}\s*=\s*(\d+)", f.read(), re.MULTILINE)
                return int(match.group(1)) if match else default
        except Exception:
            return default

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)
        self._build_sidebar()
        self._build_main_panel()
        self._build_footer()

    def _panel(self, parent, fg_color=None, border_color=None, radius=24):
        return ctk.CTkFrame(
            parent,
            fg_color=fg_color or PALETTE["surface"],
            corner_radius=radius,
            border_width=1,
            border_color=border_color or PALETTE["border"],
        )

    def _section_label(self, parent, text: str, text_color=None):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
            text_color=text_color or PALETTE["muted"],
        )

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(
            self.root,
            width=332,
            fg_color=PALETTE["sidebar"],
            corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(0, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar = sidebar

        scroll = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color="#365A77",
            scrollbar_button_hover_color="#4A708F",
        )
        scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll.grid_columnconfigure(0, weight=1)
        self.sidebar_scroll = scroll

        hero = ctk.CTkFrame(scroll, fg_color="transparent")
        hero.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 14))

        self.brand_mark = ctk.CTkLabel(
            hero,
            text="X",
            width=58,
            height=58,
            corner_radius=18,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=26, weight="bold"),
            text_color="#FFFFFF",
        )
        self.brand_mark.pack(anchor="w")

        self.hero_title = ctk.CTkLabel(
            hero,
            text=APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=25, weight="bold"),
            text_color="#F9FAFB",
        )
        self.hero_title.pack(anchor="w", pady=(14, 4))

        self.hero_subtitle = ctk.CTkLabel(
            hero,
            text=APP_SUBTITLE,
            justify="left",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color="#CBD5E1",
        )
        self.hero_subtitle.pack(anchor="w")

        self.hero_hint = ctk.CTkLabel(
            hero,
            text="围绕多平台发布、过审率、真人感、去重复和交付效率打造的医疗内容工作台。",
            justify="left",
            wraplength=248,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#94A3B8",
        )
        self.hero_hint.pack(anchor="w", pady=(10, 0))

        self.hospital_card = self._panel(scroll, fg_color=PALETTE["sidebar_card"], border_color="#355470", radius=20)
        self.hospital_card.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        hc = ctk.CTkFrame(self.hospital_card, fg_color="transparent")
        hc.pack(fill="x", padx=16, pady=16)
        self._section_label(hc, "选择医院", "#E5E7EB").pack(anchor="w", pady=(0, 12))

        self.btn_yicheng = ctk.CTkButton(
            hc,
            text="义乌义城医院",
            anchor="w",
            height=48,
            corner_radius=14,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold"),
            command=lambda: self.switch_hospital("yiwu_yicheng"),
        )
        self.btn_yicheng.pack(fill="x", pady=(0, 8))

        self.btn_weichuang = ctk.CTkButton(
            hc,
            text="义乌微创医院",
            anchor="w",
            height=48,
            corner_radius=14,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold"),
            command=lambda: self.switch_hospital("yiwu_weichuang"),
        )
        self.btn_weichuang.pack(fill="x")

        self.cfg_label = ctk.CTkLabel(
            hc,
            text="",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color="#94A3B8",
        )
        self.cfg_label.pack(anchor="w", pady=(12, 0))

        self.control_card = self._panel(scroll, fg_color=PALETTE["sidebar_card"], border_color="#355470", radius=20)
        self.control_card.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        cc = ctk.CTkFrame(self.control_card, fg_color="transparent")
        cc.pack(fill="x", padx=16, pady=16)
        self._section_label(cc, "生成设置", "#E5E7EB").pack(anchor="w", pady=(0, 12))

        count_row = ctk.CTkFrame(cc, fg_color="transparent")
        count_row.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            count_row,
            text="生成篇数",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color="#E5E7EB",
        ).pack(side="left")

        self.count_entry = ctk.CTkEntry(
            count_row,
            width=84,
            height=36,
            justify="center",
            corner_radius=10,
            border_color="#6B879E",
            fg_color="#24415A",
            text_color="#F9FAFB",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=14),
        )
        self.count_entry.pack(side="right")
        self.count_entry.insert(0, "12")

        mode_wrap = ctk.CTkFrame(cc, fg_color="transparent")
        mode_wrap.pack(fill="x")
        mode_wrap.grid_columnconfigure((0, 1), weight=1, uniform="mode")
        mode_wrap.grid_columnconfigure((2, 3), weight=1, uniform="mode")
        self._mode_btns = {}
        keys = ["all", "zhihu", "sohu", "baijiahao", "toutiao"]
        for idx, key in enumerate(keys):
            row = idx // 2 if idx < 4 else 2
            col = idx % 2 if idx < 4 else 0
            span = 1 if idx < 4 else 2
            btn = ctk.CTkButton(
                mode_wrap,
                text=PLATFORMS[key],
                height=34,
                corner_radius=10,
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
                command=lambda k=key: self._set_mode(k),
            )
            btn.grid(row=row, column=col, columnspan=span, sticky="ew", padx=4, pady=4)
            self._mode_btns[key] = btn

        self.action_card = self._panel(scroll, fg_color=PALETTE["sidebar_card"], border_color="#355470", radius=20)
        self.action_card.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        ac = ctk.CTkFrame(self.action_card, fg_color="transparent")
        ac.pack(fill="x", padx=16, pady=16)
        self._section_label(ac, "运行控制", "#E5E7EB").pack(anchor="w", pady=(0, 12))

        self.btn_start = ctk.CTkButton(
            ac,
            text="开始生成",
            height=48,
            corner_radius=14,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=15, weight="bold"),
            command=lambda: self.start_process("main"),
        )
        self.btn_start.pack(fill="x", pady=(0, 8))

        self.btn_stop = ctk.CTkButton(
            ac,
            text="停止当前任务",
            height=44,
            corner_radius=14,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            command=self.stop_process,
        )
        self.btn_stop.pack(fill="x")

        self.btn_continue = ctk.CTkButton(
            ac,
            text="继续生成剩余篇数",
            height=40,
            corner_radius=12,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
            command=self._continue_process,
        )

        self.quick_card = self._panel(scroll, fg_color=PALETTE["sidebar_card"], border_color="#355470", radius=20)
        self.quick_card.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))
        qc = ctk.CTkFrame(self.quick_card, fg_color="transparent")
        qc.pack(fill="x", padx=16, pady=16)
        qc.grid_columnconfigure((0, 1), weight=1, uniform="quick")
        self._section_label(qc, "快捷入口", "#E5E7EB").pack(anchor="w", pady=(0, 12))

        self.btn_review = ctk.CTkButton(
            qc,
            text="打开审阅台",
            height=36,
            corner_radius=12,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
            command=self._start_review,
        )
        self.btn_review.pack(fill="x", pady=(0, 8))

        quick_grid = ctk.CTkFrame(qc, fg_color="transparent")
        quick_grid.pack(fill="x")
        quick_grid.grid_columnconfigure((0, 1), weight=1, uniform="quick")

        self.btn_output = ctk.CTkButton(
            quick_grid,
            text="输出目录",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            command=lambda: self._open_path(self._output_dir()),
        )
        self.btn_output.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))

        self.btn_latest = ctk.CTkButton(
            quick_grid,
            text="最新批次",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            command=self.open_latest_output_folder,
        )
        self.btn_latest.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        self.btn_txt_dir = ctk.CTkButton(
            quick_grid,
            text="最新TXT目录",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            command=self.open_latest_txt_folder,
        )
        self.btn_txt_dir.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))

        self.btn_txt_file = ctk.CTkButton(
            quick_grid,
            text="最新TXT文件",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            command=self.open_latest_txt_file,
        )
        self.btn_txt_file.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        self.btn_logs = ctk.CTkButton(
            quick_grid,
            text="运行日志",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            command=lambda: self._open_path(self._logs_dir()),
        )
        self.btn_logs.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.sidebar_note = ctk.CTkLabel(
            scroll,
            text="适合用于知乎、搜狐、百家号、头条等平台的医疗内容批量生成，建议交付前完成一轮实跑验收。",
            wraplength=252,
            justify="left",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#94A3B8",
        )
        self.sidebar_note.grid(row=5, column=0, sticky="ew", padx=16, pady=(2, 18))

    def _build_main_panel(self):
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(16, 16), pady=(16, 8))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        self.main = main

        self.header_card = self._panel(main, fg_color=PALETTE["surface"], radius=28)
        self.header_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        header_inner = ctk.CTkFrame(self.header_card, fg_color="transparent")
        header_inner.pack(fill="x", padx=22, pady=18)
        header_inner.grid_columnconfigure(0, weight=1)
        header_inner.grid_columnconfigure(1, weight=0)

        headline = ctk.CTkFrame(header_inner, fg_color="transparent")
        headline.grid(row=0, column=0, sticky="w")

        self.header_title = ctk.CTkLabel(
            headline,
            text="文案生成器运行总览",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=23, weight="bold"),
            text_color=PALETTE["text"],
        )
        self.header_title.pack(anchor="w")

        self.header_desc = ctk.CTkLabel(
            headline,
            text="聚焦多平台适配、过审稳定性、真人表达质感、重复内容规避与交付过程可视化。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=PALETTE["muted"],
        )
        self.header_desc.pack(anchor="w", pady=(5, 0))

        header_right = ctk.CTkFrame(header_inner, fg_color="transparent")
        header_right.grid(row=0, column=1, sticky="e")

        self.hospital_badge = ctk.CTkLabel(
            header_right,
            text="",
            corner_radius=999,
            padx=18,
            pady=8,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
        )
        self.hospital_badge.pack(anchor="e", pady=(0, 10))

        status_row = ctk.CTkFrame(header_right, fg_color="transparent")
        status_row.pack(anchor="e")
        self.status_dot = ctk.CTkLabel(
            status_row,
            text="●",
            font=ctk.CTkFont(family="Segoe UI Symbol", size=15),
            text_color=PALETTE["soft"],
        )
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_text = ctk.CTkLabel(
            status_row,
            text="等待启动",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"),
            text_color=PALETTE["muted"],
        )
        self.status_text.pack(side="left")

        metric_row = ctk.CTkFrame(main, fg_color="transparent")
        metric_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(4):
            metric_row.grid_columnconfigure(i, weight=1, uniform="metric")
        self.metric_cards = {}
        metric_defs = [
            ("saved", "已保存"),
            ("progress", "完成进度"),
            ("errors", "异常记录"),
            ("runtime", "运行用时"),
        ]
        for idx, (key, title) in enumerate(metric_defs):
            card = self._panel(metric_row, fg_color=PALETTE["surface"], radius=22)
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0 if idx == 3 else 6))
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=16, pady=14)
            ctk.CTkLabel(
                inner,
                text=title,
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
                text_color=PALETTE["muted"],
            ).pack(anchor="w")
            value = ctk.CTkLabel(
                inner,
                text="0",
                font=ctk.CTkFont(family="Segoe UI Semibold", size=22, weight="bold"),
                text_color=PALETTE["text"],
            )
            value.pack(anchor="w", pady=(8, 2))
            hint = ctk.CTkLabel(
                inner,
                text="",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
                text_color=PALETTE["soft"],
            )
            hint.pack(anchor="w")
            self.metric_cards[key] = {"value": value, "hint": hint}

        self.stage_card = self._panel(main, fg_color=PALETTE["surface"], radius=24)
        self.stage_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        stage_inner = ctk.CTkFrame(self.stage_card, fg_color="transparent")
        stage_inner.pack(fill="x", padx=22, pady=18)

        stage_top = ctk.CTkFrame(stage_inner, fg_color="transparent")
        stage_top.pack(fill="x")
        self._section_label(stage_top, "当前阶段").pack(side="left")
        self.stage_label = ctk.CTkLabel(
            stage_top,
            text="准备就绪",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=16, weight="bold"),
            text_color=PALETTE["text"],
        )
        self.stage_label.pack(side="right")

        self.stage_canvas = tk.Canvas(
            stage_inner,
            height=76,
            bd=0,
            highlightthickness=0,
            bg=PALETTE["surface"],
        )
        self.stage_canvas.pack(fill="x", pady=(10, 8))

        self.progress_bar = ctk.CTkProgressBar(
            stage_inner,
            height=10,
            corner_radius=999,
            fg_color=PALETTE["surface_alt"],
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

        progress_meta = ctk.CTkFrame(stage_inner, fg_color="transparent")
        progress_meta.pack(fill="x", pady=(10, 0))
        self.stats_label = ctk.CTkLabel(
            progress_meta,
            text="已保存 0 篇 · 错误 0 条",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=PALETTE["muted"],
        )
        self.stats_label.pack(side="left")
        self.progress_pct = ctk.CTkLabel(
            progress_meta,
            text="0%",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=22, weight="bold"),
            text_color=PALETTE["text"],
        )
        self.progress_pct.pack(side="right")

        self.speed_label = ctk.CTkLabel(
            stage_inner,
            text="",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color=PALETTE["soft"],
        )
        self.speed_label.pack(anchor="w", pady=(6, 0))

        self.log_card = self._panel(main, fg_color=PALETTE["surface"], radius=24)
        self.log_card.grid(row=3, column=0, sticky="nsew")
        self.log_card.grid_columnconfigure(0, weight=1)
        self.log_card.grid_rowconfigure(1, weight=1)

        log_head = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 10))
        log_head.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(log_head, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")
        self._section_label(title_wrap, "运行日志").pack(anchor="w")
        self.log_desc = ctk.CTkLabel(
            title_wrap,
            text="采用简洁事件流展示方式，只保留关键阶段、保存进度与异常提醒，减少工程感。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color=PALETTE["soft"],
        )
        self.log_desc.pack(anchor="w", pady=(4, 0))

        self.summary_pill = ctk.CTkLabel(
            log_head,
            text="准备就绪",
            corner_radius=999,
            padx=14,
            pady=6,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["muted"],
        )
        self.summary_pill.grid(row=0, column=1, sticky="e")

        log_body = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        log_body.grid_columnconfigure(0, weight=1)
        log_body.grid_rowconfigure(0, weight=1)

        self.console = tk.Text(
            log_body,
            bd=0,
            wrap="word",
            padx=18,
            pady=16,
            relief="flat",
            highlightthickness=0,
            bg=PALETTE["log_bg"],
            fg=PALETTE["log_text"],
            insertbackground=PALETTE["log_text"],
            selectbackground="#E7DDD0",
            font=("Microsoft YaHei UI", 10),
        )
        self.console.grid(row=0, column=0, sticky="nsew")
        self.console.configure(state="disabled")
        self.console.tag_configure("muted", foreground=PALETTE["soft"], spacing1=4, spacing3=6)
        self.console.tag_configure("good", foreground=PALETTE["success"], spacing1=4, spacing3=6)
        self.console.tag_configure("warn", foreground=PALETTE["warning"], spacing1=4, spacing3=6)
        self.console.tag_configure("bad", foreground=PALETTE["danger"], spacing1=4, spacing3=6)
        self.console.tag_configure("accent", foreground=self._cfg()["accent"], spacing1=4, spacing3=6)
        self._append_line("欢迎使用 X Launcher。选择医院、设置篇数与平台后即可开始生成。", "muted")

    def _build_footer(self):
        footer = ctk.CTkFrame(self.root, fg_color="transparent")
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=24, pady=(0, 10))
        self.meta_label = ctk.CTkLabel(
            footer,
            text="准备就绪 · 请先选择医院",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color=PALETTE["muted"],
        )
        self.meta_label.pack(side="left")

        self.toast_label = ctk.CTkLabel(
            footer,
            text="",
            corner_radius=999,
            padx=14,
            pady=6,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
        )
        self.toast_label.pack(side="right")

    def _apply_theme(self):
        cfg = self._cfg()
        acc = cfg["accent"]
        deep = cfg["accent_deep"]
        soft = cfg["accent_soft"]
        line = cfg["accent_line"]

        self.brand_mark.configure(fg_color=acc)
        self.hospital_badge.configure(text=cfg["label"], fg_color=soft, text_color=deep)
        self.progress_bar.configure(progress_color=acc)
        self.progress_pct.configure(text_color=deep)
        self.stage_label.configure(text_color=deep)
        self.summary_pill.configure(fg_color=soft, text_color=deep)
        self.console.tag_configure("accent", foreground=acc)

        selected_cfg = {
            "fg_color": soft,
            "hover_color": line,
            "text_color": deep,
            "border_width": 1,
            "border_color": line,
        }
        idle_cfg = {
            "fg_color": "#1C3D5A",
            "hover_color": "#244864",
            "text_color": "#E5E7EB",
            "border_width": 1,
            "border_color": "#36566F",
        }

        if self.current_hospital == "yiwu_yicheng":
            self.btn_yicheng.configure(**selected_cfg)
            self.btn_weichuang.configure(**idle_cfg)
        else:
            self.btn_weichuang.configure(**selected_cfg)
            self.btn_yicheng.configure(**idle_cfg)

        for key, btn in self._mode_btns.items():
            if key == self._selected_mode:
                btn.configure(
                    fg_color=soft,
                    hover_color=line,
                    text_color=deep,
                    border_width=1,
                    border_color=line,
                )
            else:
                btn.configure(
                    fg_color="#1C3D5A",
                    hover_color="#244864",
                    text_color="#E5E7EB",
                    border_width=1,
                    border_color="#36566F",
                )

        self.btn_start.configure(fg_color=acc, hover_color=deep, text_color="#FFFFFF")
        self.btn_continue.configure(fg_color=acc, hover_color=deep, text_color="#FFFFFF")
        self.btn_stop.configure(
            fg_color="#FFF1F2",
            hover_color="#FFE4E6",
            text_color=PALETTE["danger"],
            border_width=1,
            border_color="#FECDD3",
        )

        quiet_buttons = [
            self.btn_review,
            self.btn_output,
            self.btn_latest,
            self.btn_txt_dir,
            self.btn_txt_file,
            self.btn_logs,
        ]
        for btn in quiet_buttons:
            btn.configure(
                fg_color=soft,
                hover_color=line,
                text_color=deep,
                border_width=1,
                border_color=line,
            )

        batch = self._read_config_int("BATCH_SIZE", 12)
        workers = self._read_config_int("CONCURRENT_WORKERS", 3)
        self.cfg_label.configure(text=f"默认批量 {batch} 篇 · 并发 {workers}")
        self._draw_stage_bar()
        self._refresh_metric_cards()

    def _set_mode(self, mode: str):
        self._selected_mode = mode
        self.count_entry.delete(0, "end")
        self.count_entry.insert(0, "3" if mode != "all" else "12")
        self._apply_theme()

    def switch_hospital(self, key: str):
        if self.process and self.process.poll() is None:
            self._show_toast("任务运行中，请先停止当前任务")
            return
        self.current_hospital = key
        self.current_stage = "准备就绪"
        self.stage_index = -1
        self.visual_progress = 0.0
        self.stage_label.configure(text=self.current_stage)
        self.status_text.configure(text="等待启动")
        self.status_dot.configure(text_color=PALETTE["soft"])
        self.meta_label.configure(text=f"{HOSPITALS[key]['label']} · 准备就绪")
        self.summary_pill.configure(text="已切换医院")
        self._append_line(f"已切换到 {HOSPITALS[key]['label']}", "accent")
        self._apply_theme()

    def _append_line(self, text: str, tag: str = ""):
        prefixes = {
            "good": "● ",
            "warn": "◐ ",
            "bad": "■ ",
            "accent": "◆ ",
            "muted": "· ",
        }
        text = f"{prefixes.get(tag, '· ')}{text}"
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _open_path(self, path: str):
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def open_latest_output_folder(self):
        output_root = self._output_dir()
        os.makedirs(output_root, exist_ok=True)
        subdirs = [
            os.path.join(output_root, name)
            for name in os.listdir(output_root)
            if os.path.isdir(os.path.join(output_root, name))
        ]
        os.startfile(max(subdirs, key=os.path.getmtime) if subdirs else output_root)

    def _find_latest_txt_file(self):
        output_root = self._output_dir()
        if not os.path.exists(output_root):
            return None
        latest_file = None
        latest_mtime = -1.0
        for root, _, files in os.walk(output_root):
            for name in files:
                if not name.lower().endswith(".txt"):
                    continue
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_file = path
        return latest_file

    def open_latest_txt_folder(self):
        latest_file = self._find_latest_txt_file()
        if latest_file:
            os.startfile(os.path.dirname(latest_file))
            return
        self._show_toast("暂未找到生成的 TXT 文件")

    def open_latest_txt_file(self):
        latest_file = self._find_latest_txt_file()
        if latest_file:
            os.startfile(latest_file)
            return
        self._show_toast("暂未找到生成的 TXT 文件")

    def _show_toast(self, text: str):
        if self._toast_after_id:
            self.root.after_cancel(self._toast_after_id)
        cfg = self._cfg()
        self.toast_label.configure(text=text, fg_color=cfg["accent_soft"], text_color=cfg["accent_deep"])
        self._toast_after_id = self.root.after(2600, lambda: self.toast_label.configure(text="", fg_color="transparent"))

    def _get_count(self) -> int:
        try:
            return max(1, int(self.count_entry.get()))
        except ValueError:
            return 12

    def _draw_stage_bar(self):
        self.stage_canvas.delete("all")
        cfg = self._cfg()
        accent = cfg["accent"]
        accent_line = cfg["accent_line"]
        w = max(self.stage_canvas.winfo_width(), 540)
        h = 76
        pad_x = 24
        usable = w - pad_x * 2
        steps = len(STAGE_STEPS)
        gap = usable / max(steps - 1, 1)
        cy = 24
        self.stage_canvas.configure(bg=PALETTE["surface"])

        for idx, label in enumerate(STAGE_STEPS):
            cx = pad_x + idx * gap
            if idx < steps - 1:
                nx = pad_x + (idx + 1) * gap
                line_color = accent if idx < self.stage_index else PALETTE["border"]
                self.stage_canvas.create_line(cx + 18, cy, nx - 18, cy, fill=line_color, width=4, capstyle=tk.ROUND)

            active = idx <= self.stage_index
            fill = accent if active else PALETTE["surface_alt"]
            outline = accent_line if active else PALETTE["border"]
            text_color = "#FFFFFF" if active else PALETTE["muted"]
            label_color = accent if active else PALETTE["muted"]
            radius = 16 if active else 14

            self.stage_canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                fill=fill,
                outline=outline,
                width=2,
            )
            self.stage_canvas.create_text(
                cx,
                cy,
                text=str(idx + 1),
                fill=text_color,
                font=("Segoe UI Semibold", 10),
            )
            self.stage_canvas.create_text(
                cx,
                h - 16,
                text=label,
                fill=label_color,
                font=("Microsoft YaHei UI", 10, "bold" if active else "normal"),
            )

    def _set_stage_by_line(self, stripped: str):
        previous = self.stage_index
        for idx, kw in enumerate(["长尾", "初稿", "去AI", "评分", "保存"]):
            if kw in stripped:
                self.stage_index = idx
                self.current_stage = STAGE_STEPS[idx]
                break
        if self.stage_index != previous:
            self.stage_started_at = datetime.now()
            self.stage_label.configure(text=self.current_stage)
            self.summary_pill.configure(text=self.current_stage)

    def _format_runtime(self) -> str:
        if not self.start_time:
            return "00:00"
        sec = int((datetime.now() - self.start_time).total_seconds())
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def _predict_stage_progress(self) -> float:
        if self.process_mode != "main" or not self.start_time:
            return 0.0
        if self.stage_index < 0:
            return 0.0

        scale = max(self.progress_target, 1) / 12
        current_span_end = STAGE_MILESTONES[min(self.stage_index, len(STAGE_MILESTONES) - 1)]
        current_span_start = 0.02 if self.stage_index == 0 else STAGE_MILESTONES[self.stage_index - 1]
        if self.stage_index >= len(STAGE_MILESTONES) - 1:
            return current_span_end

        started_at = self.stage_started_at or self.start_time
        elapsed = max((datetime.now() - started_at).total_seconds(), 0.0)
        estimated = max(BASE_STAGE_SECONDS[self.stage_index] * scale, 4.0)
        ratio = min(elapsed / estimated, 0.98)
        return current_span_start + (current_span_end - current_span_start) * ratio

    def _refresh_metric_cards(self):
        progress_pct = round(self.visual_progress * 100) if self.progress_target else 0
        self.metric_cards["saved"]["value"].configure(text=str(self.saved_count))
        self.metric_cards["saved"]["hint"].configure(text="本轮写入成功的文件数")

        self.metric_cards["progress"]["value"].configure(text=f"{progress_pct}%")
        self.metric_cards["progress"]["hint"].configure(text=f"目标 {self.progress_target} 篇")

        self.metric_cards["errors"]["value"].configure(text=str(self.error_count))
        self.metric_cards["errors"]["hint"].configure(text="运行日志中的异常计数")

        self.metric_cards["runtime"]["value"].configure(text=self._format_runtime())
        self.metric_cards["runtime"]["hint"].configure(text=self.current_run_label if self.process_mode else "等待新的任务")

    def start_process(self, mode: str):
        if self.process and self.process.poll() is None:
            self._show_toast("已有任务正在运行")
            return

        script_map = {"main": self._main_py(), "review": self._review_py()}
        script = script_map.get(mode)
        if not script or not os.path.exists(script):
            self._show_toast("未找到脚本文件")
            return

        if mode == "main":
            count = self._get_count()
            platform_only = "" if self._selected_mode == "all" else self._selected_mode
        else:
            count = 0
            platform_only = ""

        self.process_mode = mode
        self.current_run_label = (
            f"单平台 · {PLATFORMS.get(platform_only, platform_only)}"
            if platform_only else
            f"全平台 · {count} 篇"
        )
        self.saved_count = 0
        self.error_count = 0
        self.progress_target = count if mode == "main" else 0
        self._remain_target = 0
        self.run_output_baseline_ts = datetime.now().timestamp()
        self.start_time = datetime.now()
        self.stage_started_at = self.start_time
        self.current_stage = "长尾扩展"
        self.stage_index = 0

        self.visual_progress = 0.02
        self.progress_bar.set(self.visual_progress)
        self.progress_pct.configure(text="0%")
        self.speed_label.configure(text="")
        self.stage_label.configure(text=self.current_stage)
        self.status_text.configure(text="启动中")
        self.status_dot.configure(text_color=self._cfg()["accent"])
        self.summary_pill.configure(text="任务启动中")
        self.meta_label.configure(text=f"进程启动中 · {self.current_run_label}")
        self.stats_label.configure(text="已保存 0 篇 · 错误 0 条")
        self.btn_continue.pack_forget()
        self._refresh_metric_cards()

        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self._append_line("------------------------------------------------------------", "muted")
        self._append_line(
            f"[{self.start_time.strftime('%H:%M:%S')}] 启动 {self._cfg()['label']} · "
            f"{'审阅台' if mode == 'review' else self.current_run_label}",
            "accent",
        )

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            launch_cmd = [sys.executable, "--worker", "--project", self.current_hospital]
            if mode == "main":
                if platform_only:
                    launch_cmd += ["--platform", platform_only]
                launch_cmd += ["--count", str(count)]
        else:
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            python_exec = pythonw if mode == "review" and os.path.exists(pythonw) else sys.executable
            launch_cmd = [python_exec, script]
            if mode == "main":
                if platform_only:
                    launch_cmd += ["--platform", platform_only]
                launch_cmd += ["--count", str(count)]

        try:
            self.process = subprocess.Popen(
                launch_cmd,
                cwd=self._project_dir(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=env,
            )
        except Exception as exc:
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 启动失败: {exc}", "bad")
            self._show_toast(f"启动失败: {exc}")
            self.process = None
            self.process_mode = None
            self.status_text.configure(text="启动失败")
            self.status_dot.configure(text_color=PALETTE["danger"])
            self.meta_label.configure(text="进程启动失败")
            self.summary_pill.configure(text="启动失败")
            return

        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()
        self.root.after(260, self._tick_runtime)

    def stop_process(self):
        if not self.process or self.process.poll() is not None:
            return
        self._remain_target = self.progress_target - self.saved_count
        try:
            self.process.terminate()
            self._append_line("已发送停止指令，可在稍后继续生成剩余篇数。", "warn")
            self.summary_pill.configure(text="正在停止")
        except Exception as exc:
            self._append_line(f"停止失败: {exc}", "bad")

    def _continue_process(self):
        if self.process and self.process.poll() is None:
            return
        if self._remain_target <= 0:
            self._show_toast("没有剩余篇数需要生成")
            return

        script = self._main_py()
        if not os.path.exists(script):
            self._show_toast("未找到脚本文件")
            return

        count = self._remain_target
        self.process_mode = "main"
        self.current_run_label = f"继续生成 · {count} 篇"
        self.saved_count = 0
        self.error_count = 0
        self.progress_target = count
        self._remain_target = 0
        self.run_output_baseline_ts = datetime.now().timestamp()
        self.start_time = datetime.now()
        self.stage_started_at = self.start_time
        self.current_stage = "长尾扩展"
        self.stage_index = 0
        self.visual_progress = 0.02
        self.progress_bar.set(self.visual_progress)
        self.progress_pct.configure(text="0%")
        self.speed_label.configure(text="")
        self.stage_label.configure(text=self.current_stage)
        self.status_text.configure(text="启动中")
        self.status_dot.configure(text_color=self._cfg()["accent"])
        self.summary_pill.configure(text="继续任务")
        self.meta_label.configure(text=f"继续生成剩余 {count} 篇")
        self.stats_label.configure(text="已保存 0 篇 · 错误 0 条")
        self.btn_continue.pack_forget()
        self._refresh_metric_cards()

        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 继续生成 · {count} 篇", "accent")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        is_frozen = getattr(sys, "frozen", False)
        platform_only = "" if self._selected_mode == "all" else self._selected_mode
        if is_frozen:
            launch_cmd = [sys.executable, "--worker", "--project", self.current_hospital]
            if platform_only:
                launch_cmd += ["--platform", platform_only]
            launch_cmd += ["--count", str(count)]
        else:
            launch_cmd = [sys.executable, script]
            if platform_only:
                launch_cmd += ["--platform", platform_only]
            launch_cmd += ["--count", str(count)]

        try:
            self.process = subprocess.Popen(
                launch_cmd,
                cwd=self._project_dir(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=env,
            )
        except Exception as exc:
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 继续启动失败: {exc}", "bad")
            self._show_toast(f"启动失败: {exc}")
            self.process = None
            self.process_mode = None
            self.status_text.configure(text="启动失败")
            self.status_dot.configure(text_color=PALETTE["danger"])
            self.meta_label.configure(text="进程启动失败")
            self.summary_pill.configure(text="启动失败")
            return

        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()
        self.root.after(260, self._tick_runtime)

    def _read_output(self):
        try:
            if self.process and self.process.stdout:
                for line in self.process.stdout:
                    self.queue.put(("line", line.rstrip("\r\n")))
        finally:
            if self.process:
                code = self.process.wait()
                self.queue.put(("done", code))

    def _count_generated_files(self) -> int:
        output_root = self._output_dir()
        if not os.path.exists(output_root):
            return 0
        latest_dir = output_root
        subdirs = [
            os.path.join(output_root, name)
            for name in os.listdir(output_root)
            if os.path.isdir(os.path.join(output_root, name))
        ]
        if subdirs:
            latest_dir = max(subdirs, key=os.path.getmtime)
        return sum(
            1
            for name in os.listdir(latest_dir)
            if name.lower().endswith(".txt")
            and os.path.isfile(os.path.join(latest_dir, name))
            and os.path.getmtime(os.path.join(latest_dir, name)) >= self.run_output_baseline_ts
        )

    def _animate_progress(self):
        if self.process_mode == "main" and self.process and self.process.poll() is None:
            predicted = self._predict_stage_progress()
            actual_ratio = self.saved_count / max(self.progress_target, 1) if self.progress_target else 0.0
            target_progress = max(predicted, actual_ratio, self.visual_progress)
            if self.saved_count >= self.progress_target > 0:
                target_progress = max(target_progress, 0.985)

            actual = self._count_generated_files()
            if actual > self.saved_count:
                self.saved_count = actual
                actual_ratio = self.saved_count / max(self.progress_target, 1)
                target_progress = max(target_progress, actual_ratio)
                self.stats_label.configure(text=f"已保存 {self.saved_count}/{self.progress_target} 篇 · 错误 {self.error_count} 条")
                if self.start_time and self.saved_count > 0:
                    elapsed = max((datetime.now() - self.start_time).total_seconds(), 1)
                    speed = self.saved_count / elapsed * 60
                    remain = max(self.progress_target - self.saved_count, 0)
                    eta_seconds = int(remain / max(self.saved_count / elapsed, 0.01))
                    self.speed_label.configure(text=f"约 {speed:.1f} 篇/分钟 · 预计剩余 {eta_seconds // 60} 分 {eta_seconds % 60:02d} 秒")

            step = 0.006 if target_progress - self.visual_progress > 0.12 else 0.0035
            self.visual_progress = min(target_progress, self.visual_progress + step)
            self.progress_bar.set(self.visual_progress)
            self.progress_pct.configure(text=f"{round(self.visual_progress * 100)}%")
        self._draw_stage_bar()
        self._refresh_metric_cards()
        self.root.after(100, self._animate_progress)

    def _handle_line(self, line: str):
        stripped = line.strip()
        if not stripped:
            return

        if stripped.startswith("[TITLE]") or stripped.startswith("[SNIPPET]"):
            return

        if "[ERR]" in stripped or "Traceback" in stripped or "失败" in stripped:
            tag = "bad"
            self.error_count += 1
        elif "[OK]" in stripped or "Running on http://127.0.0.1:5050" in stripped:
            tag = "good"
        elif "[SAVE]" in stripped or "已保存" in stripped:
            tag = "accent"
        else:
            tag = "muted"

        self._append_line(stripped, tag)
        self._set_stage_by_line(stripped)

        if "已保存" in stripped or "[SAVE]" in stripped:
            self.saved_count = max(self.saved_count, self._count_generated_files())
            pct = self.saved_count / max(self.progress_target, 1) if self.progress_target else 0
            self.visual_progress = max(self.visual_progress, min(1.0, pct))

        if self.process_mode == "review" and "Running on http://127.0.0.1:5050" in stripped:
            self.status_text.configure(text="审阅台运行中")
            self.status_dot.configure(text_color=PALETTE["success"])
            self.summary_pill.configure(text="审阅台已启动")
            self.meta_label.configure(text="审阅台已启动 · 浏览器已打开")
        elif self.process_mode == "main":
            self.status_text.configure(text="生成中" if self.saved_count < self.progress_target else "收尾中")
            self.status_dot.configure(text_color=self._cfg()["accent"])
            self.summary_pill.configure(text=self.current_stage)
            self.meta_label.configure(text=f"生成中 · {self.current_run_label} · {self.saved_count}/{self.progress_target} 篇")

        self.stats_label.configure(text=f"已保存 {self.saved_count}/{self.progress_target} 篇 · 错误 {self.error_count} 条")
        self._refresh_metric_cards()

    def _handle_done(self, code: int):
        elapsed = self._format_runtime()
        if code == 0:
            self.stage_index = 4
            self.current_stage = "全部完成"
            self.visual_progress = 1.0
            self.stage_label.configure(text=self.current_stage)
            self.status_text.configure(text="运行完成")
            self.status_dot.configure(text_color=PALETTE["success"])
            self.summary_pill.configure(text="已完成")
            self.meta_label.configure(text=f"{self.current_run_label} · 完成 · 用时 {elapsed}")
            self.progress_bar.set(1.0)
            self.progress_pct.configure(text="100%")
            self.speed_label.configure(text=f"用时 {elapsed}")
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成", "good")
            self._show_toast(f"生成完成 · {self.progress_target} 篇 · 用时 {elapsed}")
        else:
            self.status_text.configure(text="运行中断")
            self.status_dot.configure(text_color=PALETTE["danger"])
            self.summary_pill.configure(text="已中断")
            if self.process_mode == "main" and self.saved_count < self.progress_target:
                if self._remain_target <= 0:
                    self._remain_target = self.progress_target - self.saved_count
                self.btn_continue.configure(text=f"继续生成剩余 {self._remain_target} 篇")
                self.btn_continue.pack(fill="x", pady=(10, 0))
            self.meta_label.configure(text=f"异常退出 · 退出码 {code} · 用时 {elapsed}")
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 任务中断，退出码 {code}", "bad")

        self.process = None
        self.process_mode = None
        self._draw_stage_bar()
        self._refresh_metric_cards()

    def _poll_queue(self):
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._handle_line(payload)
            elif kind == "done":
                self._handle_done(payload)
        self.root.after(70, self._poll_queue)

    def _tick_runtime(self):
        if not self.process or self.process.poll() is not None:
            return
        self.meta_label.configure(text=f"运行中 · {self._format_runtime()} · {self.saved_count}/{self.progress_target} 篇")
        self._refresh_metric_cards()
        self.root.after(1000, self._tick_runtime)

    def _start_review(self):
        if self._flask_thread and self._flask_thread.is_alive():
            webbrowser.open(f"http://127.0.0.1:{self._flask_port}")
            return

        project_dir = self._project_dir()
        shared_dir = os.path.join(ROOT_DIR, "shared")

        def run_flask():
            if project_dir not in sys.path:
                sys.path.insert(0, project_dir)
            if shared_dir not in sys.path:
                sys.path.append(shared_dir)
            import bootstrap_shared  # noqa: F401
            from review_ui import app as flask_app
            flask_app.run(host="127.0.0.1", port=self._flask_port, debug=False, use_reloader=False)

        self._flask_thread = threading.Thread(target=run_flask, daemon=True)
        self._flask_thread.start()

        def open_browser():
            webbrowser.open(f"http://127.0.0.1:{self._flask_port}")
            self._append_line(f"审阅台已启动 -> http://127.0.0.1:{self._flask_port}", "accent")
            self._show_toast("审阅台已在浏览器中打开")

        self.root.after(1500, open_browser)

    def _on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(APP_TITLE, "当前任务还在运行，关闭窗口会终止任务。\n确定关闭吗？"):
                return
            try:
                self.process.terminate()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _parse_worker_args(argv):
    platform_only = ""
    custom_count = 0
    i = 1
    while i < len(argv):
        if argv[i] == "--platform" and i + 1 < len(argv):
            platform_only = argv[i + 1]
            i += 2
        elif argv[i] == "--count" and i + 1 < len(argv):
            try:
                custom_count = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif argv[i] == "--project" and i + 1 < len(argv):
            i += 2
        else:
            i += 1
    return platform_only, custom_count


def _run_worker():
    argv = sys.argv
    platform_only, custom_count = _parse_worker_args(argv)
    project_key = "yiwu_weichuang"
    i = 1
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            project_key = argv[i + 1]
            i += 2
        else:
            i += 1

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    project_dir = os.path.join(PROJECTS_DIR, project_key)
    shared_dir = os.path.join(ROOT_DIR, "shared")

    project_prefixes = (
        "config", "modules", "profiles", "pathing",
        "project_paths", "bootstrap_shared", "main",
        "review_ui", "analyze",
    )
    for name in list(sys.modules):
        for prefix in project_prefixes:
            if name == prefix or name.startswith(prefix + "."):
                del sys.modules[name]
                break

    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    if shared_dir not in sys.path:
        sys.path.append(shared_dir)

    import bootstrap_shared  # noqa: F401
    from main import run
    run(platform_only=platform_only, custom_count=custom_count)


if __name__ == "__main__":
    if "--worker" in sys.argv[1:]:
        _run_worker()
    else:
        LauncherApp().run()
