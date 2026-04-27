import os
import re
import sys
import queue
import threading
import subprocess
import webbrowser
from datetime import datetime
import tkinter as tk
import customtkinter as ctk

APP_TITLE = "X 启动台"

if getattr(sys, "frozen", False):
    ROOT_DIR = sys._MEIPASS
else:
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECTS_DIR = os.path.join(ROOT_DIR, "projects")

HOSPITALS = {
    "yiwu_yicheng": {
        "label": "义乌义城医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_yicheng"),
        "accent": "#007aff",
        "accent_soft": "#e8f2ff",
        "accent_mid": "#b4d5fe",
        "hover": "#0066d6",
    },
    "yiwu_weichuang": {
        "label": "义乌微创医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_weichuang"),
        "accent": "#ff375f",
        "accent_soft": "#ffe8ed",
        "accent_mid": "#ffb3c1",
        "hover": "#e63054",
    },
}
PLATFORMS = {
    "all": "全平台",
    "zhihu": "知乎",
    "sohu": "搜狐",
    "baijiahao": "百家",
    "toutiao": "头条",
}
STAGE_STEPS = ["长尾扩展", "首稿生成", "去AI化", "评分重写", "保存完成"]

C_PAGE    = "#f2f2f7"
C_CARD    = "#ffffff"
C_CARD_BD = "#e5e5ea"
C_TITLE   = "#1d1d1f"
C_SUBTLE  = "#6b6b70"
C_HINT    = "#86868b"
C_BG2     = "#f2f2f7"
C_CONS_BG = "#fafafa"
C_CONS_FG = "#2c2c2e"
C_GOOD    = "#248a52"
C_WARN    = "#c27800"
C_BAD     = "#d63030"

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class LauncherApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title(APP_TITLE)
        self.root.geometry("1360x920")
        self.root.minsize(1100, 740)
        self.root.configure(fg_color=C_PAGE)

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
        self.current_stage = "待启动"
        self.current_run_label = "全量模式"
        self.stage_index = -1
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
                m = re.search(rf"^{key}\s*=\s*(\d+)", f.read(), re.MULTILINE)
                return int(m.group(1)) if m else default
        except Exception:
            return default

    # ═══════════════ UI ═══════════════

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)
        self._build_left()
        self._build_right()
        self._build_statusbar()

    def _card(self, p, **kw):
        return ctk.CTkFrame(p, corner_radius=16, fg_color=C_CARD,
                            border_width=1, border_color=C_CARD_BD, **kw)

    def _section(self, parent, text: str):
        return ctk.CTkLabel(parent, text=text,
                            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
                            text_color=C_SUBTLE)

    def _build_left(self):
        scroll = ctk.CTkScrollableFrame(self.root, width=320, fg_color="transparent",
                                        scrollbar_button_color="#d1d1d6",
                                        scrollbar_button_hover_color="#aeaeb2")
        scroll.grid(row=0, column=0, sticky="ns", padx=(24, 8), pady=10)
        scroll.grid_columnconfigure(0, weight=1)

        # ── 医院 ──
        c1 = self._card(scroll)
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        i1 = ctk.CTkFrame(c1, fg_color="transparent")
        i1.pack(fill="x", padx=18, pady=14)
        self._section(i1, "选择医院").pack(anchor="w", pady=(0, 8))

        self.btn_yicheng = ctk.CTkButton(
            i1, text="   义乌义城医院", anchor="w", height=42,
            command=lambda: self.switch_hospital("yiwu_yicheng"),
            corner_radius=12, font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
        self.btn_yicheng.pack(fill="x", pady=(0, 6))
        self.btn_weichuang = ctk.CTkButton(
            i1, text="   义乌微创医院", anchor="w", height=42,
            command=lambda: self.switch_hospital("yiwu_weichuang"),
            corner_radius=12, font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
        self.btn_weichuang.pack(fill="x")

        self.cfg_label = ctk.CTkLabel(i1, text="", font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
                                      text_color=C_HINT)
        self.cfg_label.pack(anchor="w", pady=(8, 0))

        # ── 进度 ──
        c2 = self._card(scroll)
        c2.grid(row=1, column=0, sticky="ew", pady=8)
        i2 = ctk.CTkFrame(c2, fg_color="transparent")
        i2.pack(fill="x", padx=18, pady=14)

        self.prog_title = self._section(i2, "任务进度")
        self.prog_title.pack(anchor="w", pady=(0, 6))

        self.stage_label = ctk.CTkLabel(i2, text="准备就绪",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=13), text_color=C_TITLE)
        self.stage_label.pack(anchor="w", pady=(0, 8))

        self.stage_canvas = tk.Canvas(i2, height=52, bd=0, highlightthickness=0, bg=C_CARD)
        self.stage_canvas.pack(fill="x", pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(i2, height=8, corner_radius=4,
                                               progress_color=self._cfg()["accent"], fg_color=C_BG2)
        self.progress_bar.pack(fill="x", pady=(0, 4))
        self.progress_bar.set(0)

        row_pct = ctk.CTkFrame(i2, fg_color="transparent")
        row_pct.pack(fill="x")
        self.stats_label = ctk.CTkLabel(row_pct, text="已保存 0 篇 · 错误 0 条",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color=C_HINT)
        self.stats_label.pack(side="left")
        self.progress_pct = ctk.CTkLabel(row_pct, text="0%",
                                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"),
                                         text_color=self._cfg()["accent"])
        self.progress_pct.pack(side="right")

        self.speed_label = ctk.CTkLabel(i2, text="",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=10), text_color=C_HINT)
        self.speed_label.pack(anchor="w", pady=(4, 0))

        # ── 控制 ──
        c3 = self._card(scroll)
        c3.grid(row=2, column=0, sticky="ew", pady=8)
        i3 = ctk.CTkFrame(c3, fg_color="transparent")
        i3.pack(fill="x", padx=18, pady=14)

        self._section(i3, "生成控制").pack(anchor="w", pady=(0, 8))

        # Count row
        cnt_row = ctk.CTkFrame(i3, fg_color="transparent")
        cnt_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cnt_row, text="生成篇数：", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
                     text_color=C_TITLE).pack(side="left")
        self.count_entry = ctk.CTkEntry(cnt_row, width=66, height=32, justify="center",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
                                        corner_radius=8, border_color=C_CARD_BD)
        self.count_entry.pack(side="left", padx=(8, 0))
        self.count_entry.insert(0, "12")
        ctk.CTkLabel(cnt_row, text="篇", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
                     text_color=C_HINT).pack(side="left", padx=(6, 0))

        # Mode selector — single row 5 buttons
        mode_row = ctk.CTkFrame(i3, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 10))
        for i in range(5):
            mode_row.grid_columnconfigure(i, weight=1, uniform="mode")
        self._mode_btns = {}
        keys = ["all", "zhihu", "sohu", "baijiahao", "toutiao"]
        for i, key in enumerate(keys):
            btn = ctk.CTkButton(
                mode_row, text=PLATFORMS[key], height=30,
                command=lambda k=key: self._set_mode(k),
                corner_radius=8, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
            btn.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 2, 0 if i == 4 else 2))
            self._mode_btns[key] = btn

        # Start/Stop row
        btn_row = ctk.CTkFrame(i3, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 4))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        self.btn_start = ctk.CTkButton(
            btn_row, text="▶  开始生成", height=42,
            command=lambda: self.start_process("main"),
            corner_radius=12, font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"))
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_stop = ctk.CTkButton(
            btn_row, text="■  停止", height=42, command=self.stop_process,
            corner_radius=12, font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            fg_color=C_CARD, text_color=C_BAD,
            border_width=1.5, border_color=C_BAD, hover_color="#fff0f0")
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Continue (hidden initially)
        self.btn_continue = ctk.CTkButton(
            i3, text="继续生成剩余篇数", height=36,
            command=self._continue_process, corner_radius=12,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"))

        # Review button
        self.btn_review = ctk.CTkButton(
            i3, text="审阅台（浏览器打开）", height=32,
            command=self._start_review, corner_radius=10,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
        self.btn_review.pack(fill="x", pady=(6, 0))

        # ── 快捷入口 ──
        c4 = self._card(scroll)
        c4.grid(row=3, column=0, sticky="ew")
        i4 = ctk.CTkFrame(c4, fg_color="transparent")
        i4.pack(fill="x", padx=18, pady=14)

        self._section(i4, "快捷入口").pack(anchor="w", pady=(0, 8))

        r1 = ctk.CTkFrame(i4, fg_color="transparent")
        r1.pack(fill="x", pady=(0, 4))
        r1.grid_columnconfigure(0, weight=1)
        r1.grid_columnconfigure(1, weight=1)

        self.btn_output = ctk.CTkButton(
            r1, text="output", height=30,
            command=lambda: self._open_path(self._output_dir()),
            corner_radius=8, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
        self.btn_output.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_latest = ctk.CTkButton(
            r1, text="最新生成", height=30,
            command=self.open_latest_output_folder,
            corner_radius=8, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
        self.btn_latest.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.btn_logs = ctk.CTkButton(
            i4, text="logs", height=30,
            command=lambda: self._open_path(self._logs_dir()),
            corner_radius=8, font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))
        self.btn_logs.pack(fill="x")

    def _build_right(self):
        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 24), pady=10)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)

        # Header
        topf = ctk.CTkFrame(right, fg_color="transparent")
        topf.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        left_top = ctk.CTkFrame(topf, fg_color="transparent")
        left_top.pack(side="left")
        ctk.CTkLabel(left_top, text=APP_TITLE,
                     font=ctk.CTkFont(family="Microsoft YaHei UI", size=20, weight="bold"),
                     text_color=C_TITLE).pack(side="left", padx=(0, 12))

        self.hospital_badge = ctk.CTkLabel(left_top, text="",
                                           font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
                                           corner_radius=20, padx=14, pady=5)
        self.hospital_badge.pack(side="left")

        right_top = ctk.CTkFrame(topf, fg_color="transparent")
        right_top.pack(side="right")
        self.status_dot = ctk.CTkLabel(right_top, text="●",
                                       font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
                                       text_color="#aeaeb2")
        self.status_dot.pack(side="left", padx=(0, 4))
        self.status_text = ctk.CTkLabel(right_top, text="待启动",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=12), text_color=C_SUBTLE)
        self.status_text.pack(side="left")

        # Tabs
        self.tabs = ctk.CTkTabview(right, corner_radius=14,
                                   fg_color=C_CARD, border_width=1, border_color=C_CARD_BD,
                                   segmented_button_fg_color=C_BG2,
                                   segmented_button_selected_color=self._cfg()["accent"],
                                   segmented_button_unselected_color=C_BG2,
                                   segmented_button_selected_hover_color=self._cfg()["hover"])
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.tabs.add("步骤日志")
        self.tabs.add("生成内容")
        self.tabs.set("步骤日志")

        # Tab 1: Steps
        t1 = self.tabs.tab("步骤日志")
        t1.grid_columnconfigure(0, weight=1)
        t1.grid_rowconfigure(0, weight=1)
        self.console = tk.Text(
            t1, bd=0, font=("Consolas", 10), wrap="word", padx=16, pady=12,
            bg=C_CONS_BG, fg=C_CONS_FG, insertbackground=C_CONS_FG,
            relief="flat", highlightthickness=0, selectbackground="#dcdce0")
        self.console.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.console.configure(state="disabled")
        self.console.tag_configure("muted", foreground="#8e8e93")
        self.console.tag_configure("good", foreground=C_GOOD)
        self.console.tag_configure("warn", foreground=C_WARN)
        self.console.tag_configure("bad", foreground=C_BAD)
        self.console.tag_configure("accent", foreground=self._cfg()["accent"])
        self._append_line(" 欢迎使用 X 启动台 · 选择医院 · 设置篇数 · 选模式 · 点击开始生成", "muted")

        # Tab 2: Content
        t2 = self.tabs.tab("生成内容")
        t2.grid_columnconfigure(0, weight=1)
        t2.grid_rowconfigure(0, weight=1)
        self.stream_text = tk.Text(
            t2, bd=0, font=("Microsoft YaHei UI", 11), wrap="word", padx=16, pady=12,
            bg=C_CONS_BG, fg=C_CONS_FG, insertbackground=C_CONS_FG,
            relief="flat", highlightthickness=0, selectbackground="#dcdce0")
        self.stream_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.stream_text.configure(state="disabled")
        self.stream_text.tag_configure("title", font=("Microsoft YaHei UI", 12, "bold"),
                                       foreground=C_TITLE, spacing1=8, spacing3=4)
        self.stream_text.tag_configure("body", font=("Microsoft YaHei UI", 10),
                                       foreground="#4a4a4e", lmargin1=16, lmargin2=16, spacing1=2)
        self.stream_text.tag_configure("sep", foreground="#dcdce0",
                                       font=("Microsoft YaHei UI", 2), spacing1=4)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.root, height=36, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=28, pady=(0, 8))
        self.meta_label = ctk.CTkLabel(bar, text="准备就绪 · 请先选择医院",
                                       font=ctk.CTkFont(family="Microsoft YaHei UI", size=11), text_color=C_HINT)
        self.meta_label.pack(side="left")
        self.toast_label = ctk.CTkLabel(bar, text="",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"),
                                        corner_radius=8, padx=12, pady=4)
        self.toast_label.pack(side="right")

    # ═══════════════ THEME ═══════════════

    def _apply_theme(self):
        cfg = self._cfg()
        acc, hov, soft, mid = cfg["accent"], cfg["hover"], cfg["accent_soft"], cfg["accent_mid"]

        self.hospital_badge.configure(text=cfg["label"], fg_color=soft, text_color=acc)

        if self.current_hospital == "yiwu_yicheng":
            self.btn_yicheng.configure(fg_color=soft, hover_color=mid, text_color=acc,
                                       font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"))
            self.btn_weichuang.configure(fg_color=C_CARD, hover_color=C_BG2, text_color=C_HINT,
                                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
        else:
            self.btn_weichuang.configure(fg_color=soft, hover_color=mid, text_color=acc,
                                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"))
            self.btn_yicheng.configure(fg_color=C_CARD, hover_color=C_BG2, text_color=C_HINT,
                                       font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))

        self.progress_bar.configure(progress_color=acc)
        self.progress_pct.configure(text_color=acc)
        self.btn_start.configure(fg_color=acc, hover_color=hov, text_color="#ffffff")
        self.btn_continue.configure(fg_color=acc, hover_color=hov, text_color="#ffffff")

        self.tabs.configure(segmented_button_selected_color=acc,
                            segmented_button_selected_hover_color=hov)

        # Mode buttons
        for k, btn in self._mode_btns.items():
            if k == self._selected_mode:
                btn.configure(fg_color=soft, hover_color=mid, text_color=acc,
                              font=ctk.CTkFont(family="Microsoft YaHei UI", size=11, weight="bold"))
            else:
                btn.configure(fg_color=C_BG2, hover_color=mid, text_color=C_TITLE,
                              font=ctk.CTkFont(family="Microsoft YaHei UI", size=11))

        for btn in [self.btn_review, self.btn_output, self.btn_latest, self.btn_logs]:
            btn.configure(fg_color=C_BG2, hover_color=mid, text_color=C_TITLE)

        self.console.tag_configure("accent", foreground=acc)

        batch = self._read_config_int("BATCH_SIZE", 12)
        workers = self._read_config_int("CONCURRENT_WORKERS", 3)
        self.cfg_label.configure(text=f"{batch} 篇 / {workers} 并发")

    # ═══════════════ LOGIC ═══════════════

    def _set_mode(self, mode: str):
        self._selected_mode = mode
        self.count_entry.delete(0, "end")
        self.count_entry.insert(0, "3" if mode != "all" else "12")
        self._apply_theme()

    def switch_hospital(self, key: str):
        if self.process and self.process.poll() is None:
            self._show_toast("任务运行中，请先停止")
            return
        self.current_hospital = key
        self._apply_theme()
        self.stage_canvas.delete("all")
        self.stage_label.configure(text="准备就绪")
        self.stage_index = -1
        self._append_line(f"已切换到 {HOSPITALS[key]['label']}", "accent")
        self.meta_label.configure(text=f"{HOSPITALS[key]['label']} · 准备就绪")

    def _append_line(self, text: str, tag: str = ""):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _append_stream(self, text: str, tag: str = ""):
        self.stream_text.configure(state="normal")
        self.stream_text.insert("end", text, tag)
        self.stream_text.see("end")
        self.stream_text.configure(state="disabled")

    def _open_path(self, path: str):
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def open_latest_output_folder(self):
        output_root = self._output_dir()
        os.makedirs(output_root, exist_ok=True)
        subdirs = [os.path.join(output_root, name) for name in os.listdir(output_root)
                   if os.path.isdir(os.path.join(output_root, name))]
        os.startfile(max(subdirs, key=os.path.getmtime) if subdirs else output_root)

    def _show_toast(self, text: str):
        if self._toast_after_id:
            self.root.after_cancel(self._toast_after_id)
        cfg = self._cfg()
        self.toast_label.configure(text=text, fg_color=cfg["accent_soft"], text_color=cfg["accent"])
        self._toast_after_id = self.root.after(2600, lambda: self.toast_label.configure(text=""))

    def _get_count(self) -> int:
        try:
            return max(1, int(self.count_entry.get()))
        except ValueError:
            return 12

    def _draw_stage_bar(self):
        self.stage_canvas.delete("all")
        acc = self._cfg()["accent"]
        mid = self._cfg()["accent_mid"]
        w = max(self.stage_canvas.winfo_width(), 280)
        n = len(STAGE_STEPS)
        gap = w / n
        for i, label in enumerate(STAGE_STEPS):
            cx = gap * i + gap / 2
            cy = 24
            if i < n - 1:
                self.stage_canvas.create_line(cx + 13, cy, gap * (i + 1) + gap / 2 - 13, cy,
                                              fill=acc if i < self.stage_index else C_CARD_BD, width=3)
            if i <= self.stage_index:
                fill, r, fw, nc, lc = acc, 13, "bold", "#ffffff", acc
            else:
                fill, r, fw, nc, lc = C_BG2, 11, "normal", C_HINT, C_HINT
            self.stage_canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                          fill=fill, outline=mid if i <= self.stage_index else C_CARD_BD, width=2)
            self.stage_canvas.create_text(cx, cy, text=str(i + 1), fill=nc,
                                          font=("Microsoft YaHei UI", 9, fw))
            self.stage_canvas.create_text(cx, cy + 24, text=label, fill=lc,
                                          font=("Microsoft YaHei UI", 9, fw))

    def _set_stage_by_line(self, stripped: str):
        prev = self.stage_index
        for idx, kw in enumerate(["长尾", "初稿", "去AI", "评分", "保存"]):
            if kw in stripped:
                self.stage_index = idx
                self.current_stage = STAGE_STEPS[idx]
                break
        if self.stage_index != prev:
            self.stage_label.configure(text=self.current_stage)

    # ═══════════════ PROCESS ═══════════════

    def start_process(self, mode: str):
        if self.process and self.process.poll() is None:
            self._show_toast("已有任务在运行")
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
        self.current_run_label = f"单平台 · {PLATFORMS.get(platform_only, platform_only)}" if platform_only else f"全平台 · {count} 篇"
        self.saved_count = self.error_count = 0
        self.progress_target = count if mode == "main" else 0
        self._remain_target = 0
        self.run_output_baseline_ts = datetime.now().timestamp()
        self.start_time = datetime.now()
        self.progress_bar.set(0)
        self.progress_pct.configure(text="0%")
        self.speed_label.configure(text="")
        self.current_stage = "长尾扩展"
        self.stage_index = 0
        self.stage_label.configure(text=self.current_stage)
        self.stats_label.configure(text="已保存 0 篇 · 错误 0 条")
        self.status_text.configure(text="启动中")
        self.status_dot.configure(text_color=self._cfg()["accent"])
        self.meta_label.configure(text=f"进程启动中…（{self.current_run_label}）")
        self.btn_continue.pack_forget()

        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.stream_text.configure(state="normal")
        self.stream_text.delete("1.0", "end")
        self.stream_text.configure(state="disabled")

        self._append_line("─" * 60, "muted")
        self._append_line(
            f"[{self.start_time.strftime('%H:%M:%S')}] 启动 {self._cfg()['label']} · "
            f"{'审阅台' if mode == 'review' else self.current_run_label}", "accent")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            # Bundled EXE: launch self in worker mode
            launch_cmd = [sys.executable, "--worker", "--project", self.current_hospital]
            if mode == "main":
                if platform_only:
                    launch_cmd += ["--platform", platform_only]
                launch_cmd += ["--count", str(count)]
        else:
            # Dev mode: use Python interpreter
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            python_exec = pythonw if mode == "review" and os.path.exists(pythonw) else sys.executable
            launch_cmd = [python_exec, script]
            if mode == "main":
                if platform_only:
                    launch_cmd += ["--platform", platform_only]
                launch_cmd += ["--count", str(count)]

        try:
            self.process = subprocess.Popen(
                launch_cmd, cwd=self._project_dir(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=creationflags, env=env)
        except Exception as exc:
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 启动失败：{exc}", "bad")
            self._show_toast(f"启动失败：{exc}")
            self.process = None
            self.process_mode = None
            self.status_text.configure(text="启动失败")
            self.status_dot.configure(text_color=C_BAD)
            self.meta_label.configure(text="进程启动失败")
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
            self._append_line("已发送停止指令 — 可点击「继续生成」补完剩余", "warn")
        except Exception as exc:
            self._append_line(f"停止失败：{exc}", "bad")

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
        self.current_run_label = f"继续 · {count} 篇"
        self.saved_count = self.error_count = 0
        self.progress_target = count
        self._remain_target = 0
        self.run_output_baseline_ts = datetime.now().timestamp()
        self.start_time = datetime.now()
        self.progress_bar.set(0)
        self.progress_pct.configure(text="0%")
        self.speed_label.configure(text="")
        self.current_stage = "长尾扩展"
        self.stage_index = 0
        self.stage_label.configure(text=self.current_stage)
        self.stats_label.configure(text="已保存 0 篇 · 错误 0 条")
        self.status_text.configure(text="启动中")
        self.status_dot.configure(text_color=self._cfg()["accent"])
        self.meta_label.configure(text=f"继续生成剩余 {count} 篇…")
        self.btn_continue.pack_forget()

        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.stream_text.configure(state="normal")
        self.stream_text.delete("1.0", "end")
        self.stream_text.configure(state="disabled")

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
                launch_cmd, cwd=self._project_dir(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=creationflags, env=env)
        except Exception as exc:
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 继续启动失败：{exc}", "bad")
            self._show_toast(f"启动失败：{exc}")
            self.process = None
            self.process_mode = None
            self.status_text.configure(text="启动失败")
            self.status_dot.configure(text_color=C_BAD)
            self.meta_label.configure(text="进程启动失败")
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
        subdirs = [os.path.join(output_root, name) for name in os.listdir(output_root)
                   if os.path.isdir(os.path.join(output_root, name))]
        if subdirs:
            latest_dir = max(subdirs, key=os.path.getmtime)
        return sum(1 for name in os.listdir(latest_dir)
                   if name.lower().endswith('.txt')
                   and os.path.isfile(os.path.join(latest_dir, name))
                   and os.path.getmtime(os.path.join(latest_dir, name)) >= self.run_output_baseline_ts)

    def _animate_progress(self):
        if self.process_mode == "main" and self.process and self.process.poll() is None:
            actual = self._count_generated_files()
            if actual > self.saved_count:
                self.saved_count = actual
                pct = self.saved_count / max(self.progress_target, 1)
                self.progress_bar.set(pct)
                self.progress_pct.configure(text=f"{round(pct * 100)}%")
                self.stats_label.configure(
                    text=f"已保存 {self.saved_count}/{self.progress_target} 篇 · 错误 {self.error_count} 条")
                if self.start_time and self.saved_count > 0:
                    elapsed = max((datetime.now() - self.start_time).total_seconds(), 1)
                    speed = self.saved_count / elapsed * 60
                    eta_min = int((self.progress_target - self.saved_count) / max(speed / 60, 0.01) // 60)
                    self.speed_label.configure(text=f"≈ {speed:.1f} 篇/分  ·  预计剩余 {eta_min} 分")
        self._draw_stage_bar()
        self.root.after(90, self._animate_progress)

    def _handle_line(self, line: str):
        stripped = line.strip()
        # Streaming
        if stripped.startswith("[TITLE]"):
            self._append_stream(f"\n{stripped[8:].strip()}\n", "title")
            return
        if stripped.startswith("[SNIPPET]"):
            self._append_stream(f"  {stripped[10:].strip()}\n", "body")
            return

        # Status
        if "[ERR]" in stripped or "Traceback" in stripped or "失败" in stripped:
            tag, self.error_count = "bad", self.error_count + 1
        elif "[OK]" in stripped or "Running on http://127.0.0.1:5050" in stripped:
            tag = "good"
        else:
            tag = "muted"
        self._append_line(stripped if stripped else "", tag)
        self._set_stage_by_line(stripped)

        if "已保存" in stripped or "[SAVE]" in stripped:
            self.saved_count += 1
            self.progress_bar.set(min(1.0, self.saved_count / max(self.progress_target, 1)))
            self.progress_pct.configure(text=f"{round(self.saved_count / max(self.progress_target, 1) * 100)}%")

        if self.process_mode == "review" and "Running on http://127.0.0.1:5050" in stripped:
            self.status_text.configure(text="审阅台运行中")
            self.meta_label.configure(text="审阅台已启动 · 浏览器已打开")
            self.status_dot.configure(text_color=C_GOOD)
        elif self.process_mode == "main":
            self.status_text.configure(text="收尾中" if self.saved_count >= self.progress_target else "生成中")
            self.meta_label.configure(
                text=f"生成中 · {self.current_run_label} · {self.saved_count}/{self.progress_target} 篇")
            self.status_dot.configure(text_color=self._cfg()["accent"])
        self.stats_label.configure(text=f"已保存 {self.saved_count}/{self.progress_target} 篇 · 错误 {self.error_count} 条")

    def _handle_done(self, code: int):
        elapsed = "-"
        if self.start_time:
            sec = int((datetime.now() - self.start_time).total_seconds())
            elapsed = f"{sec // 60}分{sec % 60:02d}秒"
        if code == 0:
            self.stage_index = 4
            self.stage_label.configure(text="全部完成")
            self.status_text.configure(text="运行完成")
            self.status_dot.configure(text_color=C_GOOD)
            self.meta_label.configure(text=f"{self.current_run_label} · 完成 · 用时 {elapsed}")
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成", "good")
            self.progress_bar.set(1.0)
            self.progress_pct.configure(text="100%")
            self.speed_label.configure(text=f"用时 {elapsed}")
            self._show_toast(f"生成完成 · {self.progress_target} 篇 · {elapsed}")
        else:
            self.status_text.configure(text="运行中断")
            self.status_dot.configure(text_color=C_BAD)
            if self.process_mode == "main" and self.saved_count < self.progress_target:
                if self._remain_target <= 0:
                    self._remain_target = self.progress_target - self.saved_count
                self.btn_continue.configure(text=f"继续生成剩余 {self._remain_target} 篇")
                self.btn_continue.pack(fill="x", pady=(4, 0), before=self.btn_review)
            self.meta_label.configure(text=f"异常退出 · 退出码 {code} · 用时 {elapsed}")
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 任务中断，退出码 {code}", "bad")
        self.process = None
        self.process_mode = None

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
        if self.start_time:
            sec = int((datetime.now() - self.start_time).total_seconds())
            self.meta_label.configure(
                text=f"运行中 · {sec // 60}分{sec % 60:02d}秒 · {self.saved_count}/{self.progress_target} 篇")
        self.root.after(1000, self._tick_runtime)

    # ═══════════════ REVIEW ═══════════════

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
            self._append_line(f"审阅台已启动 → http://127.0.0.1:{self._flask_port}", "accent")
            self._show_toast("审阅台已在浏览器中打开")

        self.root.after(1500, open_browser)

    # ═══════════════ CLOSE ═══════════════

    def _on_close(self):
        if self.process and self.process.poll() is None:
            from tkinter import messagebox
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
            global WORKER_PROJECT
            WORKER_PROJECT = argv[i + 1]
            i += 2
        else:
            i += 1
    return platform_only, custom_count


def _run_worker():
    argv = sys.argv
    platform_only, custom_count = _parse_worker_args(argv)
    project_key = "yiwu_weichuang"  # default
    i = 1
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            project_key = argv[i + 1]
            i += 2
        else:
            i += 1

    # 确保 worker 模式下 stdout/stderr 可用
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    project_dir = os.path.join(PROJECTS_DIR, project_key)
    shared_dir = os.path.join(ROOT_DIR, "shared")

    # 清除可能被 PyInstaller 冻结的旧项目模块缓存，防止品牌名串味
    _PROJ_PREFIXES = (
        "config", "modules", "profiles", "pathing",
        "project_paths", "bootstrap_shared", "main",
        "review_ui", "analyze",
    )
    for _k in list(sys.modules):
        for _pfx in _PROJ_PREFIXES:
            if _k == _pfx or _k.startswith(_pfx + "."):
                del sys.modules[_k]
                break

    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    if shared_dir not in sys.path:
        sys.path.append(shared_dir)

    import bootstrap_shared
    from main import run
    run(platform_only=platform_only, custom_count=custom_count)


if __name__ == "__main__":
    argv = sys.argv
    is_worker = "--worker" in argv[1:]
    if is_worker:
        # Worker mode — run generation script directly (called by subprocess)
        _run_worker()
    else:
        LauncherApp().run()
