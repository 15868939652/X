import os
import re
import sys
import queue
import threading
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

APP_TITLE = "X 启动台"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(ROOT_DIR, "projects")
HOSPITALS = {
    "yiwu_yicheng": {
        "label": "义乌义城医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_yicheng"),
        "theme": {
            "page_bg": "#eef6ff",
            "panel_bg": "#ffffff",
            "hero_bg": "#dcebff",
            "hero_accent": "#7db8ff",
            "primary": "#74aefb",
            "primary_dark": "#5798ef",
            "primary_soft": "#e7f2ff",
            "text": "#16324f",
            "muted": "#67809a",
            "border": "#d7e6fb",
            "console_bg": "#0e1726",
            "console_fg": "#d7e4ff",
            "success": "#2db67c",
            "warning": "#d7a231",
            "danger": "#d95c6a",
            "toast": "#74aefb",
        },
    },
    "yiwu_weichuang": {
        "label": "义乌微创医院",
        "dir": os.path.join(PROJECTS_DIR, "yiwu_weichuang"),
        "theme": {
            "page_bg": "#fff4f7",
            "panel_bg": "#ffffff",
            "hero_bg": "#ffe4ec",
            "hero_accent": "#f3a9bb",
            "primary": "#ef9ab0",
            "primary_dark": "#e47f98",
            "primary_soft": "#fff0f5",
            "text": "#4a2230",
            "muted": "#8b6672",
            "border": "#f7d7e1",
            "console_bg": "#18111a",
            "console_fg": "#ffe7ef",
            "success": "#2db67c",
            "warning": "#d7a231",
            "danger": "#d95c6a",
            "toast": "#ef9ab0",
        },
    },
}
PLATFORMS = [("zhihu", "知乎"), ("sohu", "搜狐"), ("baijiahao", "百家号"), ("toutiao", "头条")]


class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1240x860")
        self.root.minsize(1120, 760)

        self.process = None
        self.process_mode = None
        self.current_hospital = "yiwu_yicheng"
        self.reader_thread = None
        self.queue = queue.Queue()
        self.start_time = None
        self.saved_count = 0
        self.error_count = 0
        self.current_run_label = "全量模式（12篇）"
        self.current_stage = "待启动"
        self.progress_target = 12
        self.run_output_baseline_ts = 0.0
        self.stage_steps = ["长尾扩展", "首稿生成", "去AI化", "评分重写", "保存完成"]
        self.stage_index = 0

        self.status_text = tk.StringVar(value="待启动")
        self.meta_text = tk.StringVar(value="准备就绪，先选择医院再开始。")
        self.stats_text = tk.StringVar(value="已保存 0 篇 · 错误 0 条")
        self.mode_text = tk.StringVar(value="主生成模式")
        self.hospital_text = tk.StringVar(value=HOSPITALS[self.current_hospital]["label"])
        self.cfg_text = tk.StringVar(value=self._build_cfg_text())
        self.progress_text = tk.StringVar(value="0%")
        self.progress_value = tk.DoubleVar(value=0)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._apply_theme()
        self.root.after(80, self._poll_queue)
        self.root.after(120, self._animate_progress)

    def _theme(self):
        return HOSPITALS[self.current_hospital]["theme"]

    def _project_dir(self):
        return HOSPITALS[self.current_hospital]["dir"]

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
            text = open(self._config_path(), "r", encoding="utf-8").read()
            m = re.search(rf"^{key}\s*=\s*(\d+)", text, re.MULTILINE)
            return int(m.group(1)) if m else default
        except Exception:
            return default

    def _build_cfg_text(self) -> str:
        batch_size = self._read_config_int("BATCH_SIZE", 12)
        workers = self._read_config_int("CONCURRENT_WORKERS", 3)
        return f"医院 = {HOSPITALS[self.current_hospital]['label']}\nBATCH_SIZE = {batch_size}\nCONCURRENT_WORKERS = {workers}\noutput\\\nlogs\\"

    def _mk_button(self, parent, text, command, width=10):
        btn = tk.Button(parent, text=text, command=command, bd=0, relief="flat", cursor="hand2", font=("Microsoft YaHei UI", 10), width=width, padx=10, pady=7)
        return btn

    def _build_ui(self):
        self.outer = tk.Frame(self.root)
        self.outer.pack(fill="both", expand=True, padx=16, pady=14)

        self.header = tk.Frame(self.outer)
        self.header.pack(fill="x")
        self.title_label = tk.Label(self.header, text=APP_TITLE, font=("Microsoft YaHei UI", 28, "bold"))
        self.title_label.pack(anchor="w")
        self.subtitle_label = tk.Label(self.header, text="一个入口，分别启动两家医院独立项目；支持全量与单平台生成。", font=("Microsoft YaHei UI", 10))
        self.subtitle_label.pack(anchor="w", pady=(6, 0))

        self.hero = tk.Frame(self.outer, bd=0, relief="flat")
        self.hero.pack(fill="x", pady=(12, 10))
        self.hero_left = tk.Frame(self.hero)
        self.hero_left.pack(side="left", fill="both", expand=True, padx=18, pady=16)
        self.hero_right = tk.Frame(self.hero)
        self.hero_right.pack(side="right", padx=18, pady=16)
        self.hero_tag = tk.Label(self.hero_left, text="当前医院", font=("Microsoft YaHei UI", 10))
        self.hero_tag.pack(anchor="w")
        self.hero_hospital = tk.Label(self.hero_left, textvariable=self.hospital_text, font=("Microsoft YaHei UI", 26, "bold"))
        self.hero_hospital.pack(anchor="w", pady=(8, 0))
        self.hero_mode = tk.Label(self.hero_left, textvariable=self.mode_text, font=("Microsoft YaHei UI", 10), padx=12, pady=6)
        self.hero_mode.pack(anchor="w", pady=(14, 0))
        self.hero_status = tk.Label(self.hero_right, textvariable=self.status_text, font=("Microsoft YaHei UI", 18, "bold"))
        self.hero_status.pack(anchor="e")
        self.hero_meta = tk.Label(self.hero_right, textvariable=self.meta_text, font=("Microsoft YaHei UI", 10), justify="right")
        self.hero_meta.pack(anchor="e", pady=(6, 0))

        self.content = tk.Frame(self.outer)
        self.content.pack(fill="both", expand=True)

        self.left_col = tk.Frame(self.content)
        self.left_col.pack(side="left", fill="both", expand=True)
        self.right_col = tk.Frame(self.content, width=300)
        self.right_col.pack(side="left", fill="y", padx=(16, 0))
        self.right_col.pack_propagate(False)

        self.card_hospital = tk.Frame(self.left_col, bd=0, relief="flat")
        self.card_hospital.pack(fill="x", pady=(0, 8))
        self.card_hospital_inner = tk.Frame(self.card_hospital)
        self.card_hospital_inner.pack(fill="x", padx=18, pady=16)
        self.hospital_title = tk.Label(self.card_hospital_inner, text="医院切换", font=("Microsoft YaHei UI", 11, "bold"))
        self.hospital_title.pack(anchor="w")
        self.hospital_btns = tk.Frame(self.card_hospital_inner)
        self.hospital_btns.pack(fill="x", pady=(12, 0))
        self.btn_h1 = self._mk_button(self.hospital_btns, "义乌义城医院", lambda: self.switch_hospital("yiwu_yicheng"), 14)
        self.btn_h1.pack(side="left")
        self.btn_h2 = self._mk_button(self.hospital_btns, "义乌微创医院", lambda: self.switch_hospital("yiwu_weichuang"), 14)
        self.btn_h2.pack(side="left", padx=(10, 0))

        self.card_progress = tk.Frame(self.left_col)
        self.card_progress.pack(fill="x", pady=(0, 8))
        self.card_progress_inner = tk.Frame(self.card_progress)
        self.card_progress_inner.pack(fill="x", padx=18, pady=16)
        tk.Label(self.card_progress_inner, text="任务进度", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.stage_label = tk.Label(self.card_progress_inner, text="当前阶段：待启动", font=("Microsoft YaHei UI", 10))
        self.stage_label.pack(anchor="w", pady=(8, 0))
        tk.Label(self.card_progress_inner, textvariable=self.stats_text, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(6, 0))
        self.stage_canvas = tk.Canvas(self.card_progress_inner, height=36, highlightthickness=0, bd=0)
        self.stage_canvas.pack(fill="x", pady=(12, 0))
        self.stage_items = []
        self.progress_canvas = tk.Canvas(self.card_progress_inner, height=16, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x", pady=(10, 0))
        self.progress_bar_bg = self.progress_canvas.create_rectangle(0, 0, 100, 16, outline="")
        self.progress_bar_fg = self.progress_canvas.create_rectangle(0, 0, 0, 16, outline="")
        self.progress_pct = tk.Label(self.card_progress_inner, textvariable=self.progress_text, font=("Microsoft YaHei UI", 10, "bold"))
        self.progress_pct.pack(anchor="e", pady=(6, 0))

        self.card_actions = tk.Frame(self.left_col)
        self.card_actions.pack(fill="x", pady=(0, 8))
        self.card_actions_inner = tk.Frame(self.card_actions)
        self.card_actions_inner.pack(fill="x", padx=18, pady=16)
        tk.Label(self.card_actions_inner, text="主操作", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.actions_row = tk.Frame(self.card_actions_inner)
        self.actions_row.pack(fill="x", pady=(12, 0))
        self.btn_main = self._mk_button(self.actions_row, "开始生成（12篇）", lambda: self.start_process("main"), 13)
        self.btn_main.pack(side="left")
        self.btn_review = self._mk_button(self.actions_row, "启动审阅台", lambda: self.start_process("review"), 11)
        self.btn_review.pack(side="left", padx=(10, 0))
        self.btn_stop = self._mk_button(self.actions_row, "停止当前任务", self.stop_process, 11)
        self.btn_stop.pack(side="left", padx=(10, 0))
        self.file_row = tk.Frame(self.card_actions_inner)
        self.file_row.pack(fill="x", pady=(10, 0))
        self.btn_output = self._mk_button(self.file_row, "打开 output", lambda: self._open_path(self._output_dir()), 11)
        self.btn_output.pack(side="left")
        self.btn_latest = self._mk_button(self.file_row, "打开已生成文件夹", self.open_latest_output_folder, 16)
        self.btn_latest.pack(side="left", padx=(10, 0))
        self.btn_logs = self._mk_button(self.file_row, "打开 logs", lambda: self._open_path(self._logs_dir()), 10)
        self.btn_logs.pack(side="left", padx=(10, 0))

        self.platform_hint = tk.Label(self.card_actions_inner, text="按平台生成（每次 3 篇）", font=("Microsoft YaHei UI", 10, "bold"))
        self.platform_hint.pack(anchor="w", pady=(10, 0))
        self.platform_row = tk.Frame(self.card_actions_inner)
        self.platform_row.pack(fill="x", pady=(8, 0))
        self.platform_buttons = []
        for key, label in PLATFORMS:
            btn = self._mk_button(self.platform_row, label, lambda p=key: self.start_process("main", p), 8)
            btn.pack(side="left", padx=(0 if key == "zhihu" else 8, 0))
            self.platform_buttons.append(btn)

        self.card_console = tk.Frame(self.left_col)
        self.card_console.pack(fill="both", expand=True)
        self.card_console_inner = tk.Frame(self.card_console)
        self.card_console_inner.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(self.card_console_inner, text="实时输出", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.console = tk.Text(self.card_console_inner, bd=0, font=("Consolas", 10), wrap="word", padx=12, pady=12)
        self.console.pack(fill="both", expand=True, pady=(12, 0))
        self.console.tag_configure("muted")
        self.console.tag_configure("good")
        self.console.tag_configure("warn")
        self.console.tag_configure("bad")
        self._append_line("准备就绪，先选择医院，再点击上方按钮开始。", "muted")

        self.card_config = tk.Frame(self.right_col)
        self.card_config.pack(fill="x", pady=(0, 8))
        self.card_config_inner = tk.Frame(self.card_config)
        self.card_config_inner.pack(fill="x", padx=18, pady=16)
        tk.Label(self.card_config_inner, text="当前配置", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.cfg_box = tk.Text(self.card_config_inner, height=12, bd=0, font=("Consolas", 10), wrap="word")
        self.cfg_box.pack(fill="x", pady=(12, 0))
        self._refresh_cfg_box()

        self.card_finish = tk.Frame(self.right_col)
        self.card_finish.pack(fill="x")
        self.card_finish_inner = tk.Frame(self.card_finish)
        self.card_finish_inner.pack(fill="x", padx=18, pady=16)
        tk.Label(self.card_finish_inner, text="完成提示", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.finish_hint = tk.Label(self.card_finish_inner, text="运行完成后，会高亮『打开已生成文件夹』，并自动弹出完成提示。", justify="left", wraplength=230, font=("Microsoft YaHei UI", 10))
        self.finish_hint.pack(anchor="w", pady=(12, 0))

        self.toast = tk.Label(self.root, text="", font=("Microsoft YaHei UI", 10), padx=16, pady=10, bd=0)
        self.toast.place_forget()

    def _apply_theme(self):
        t = self._theme()
        self.root.configure(bg=t["page_bg"])
        self.outer.configure(bg=t["page_bg"])
        self.header.configure(bg=t["page_bg"])
        self.title_label.configure(bg=t["page_bg"], fg=t["text"])
        self.subtitle_label.configure(bg=t["page_bg"], fg=t["muted"])
        self.hero.configure(bg=t["hero_bg"], highlightbackground=t["border"], highlightthickness=1)
        self.hero_left.configure(bg=t["hero_bg"])
        self.hero_right.configure(bg=t["hero_bg"])
        self.hero_tag.configure(bg=t["hero_bg"], fg=t["muted"])
        self.hero_hospital.configure(bg=t["hero_bg"], fg=t["text"])
        self.hero_mode.configure(bg=t["hero_accent"], fg="#ffffff")
        self.hero_status.configure(bg=t["hero_bg"], fg=t["text"])
        self.hero_meta.configure(bg=t["hero_bg"], fg=t["muted"])
        self.content.configure(bg=t["page_bg"])
        self.left_col.configure(bg=t["page_bg"])
        self.right_col.configure(bg=t["page_bg"])

        card_list = [
            self.card_hospital, self.card_progress, self.card_actions,
            self.card_console, self.card_config, self.card_finish,
            self.card_hospital_inner, self.card_progress_inner, self.card_actions_inner,
            self.card_console_inner, self.card_config_inner,
            self.card_finish_inner, self.hospital_btns, self.actions_row, self.file_row,
            self.platform_row,
        ]
        for widget in card_list:
            widget.configure(bg=t["panel_bg"])

        text_widgets = [
            self.hospital_title, self.finish_hint,
        ]
        for widget in text_widgets:
            widget.configure(bg=t["panel_bg"], fg=t["text"] if widget is self.hospital_title else t["muted"])

        self.status_text.set(self.status_text.get())
        self.meta_text.set(self.meta_text.get())
        self.stats_text.set(self.stats_text.get())
        self.progress_pct.configure(bg=t["panel_bg"], fg=t["primary_dark"])
        self.cfg_box.configure(bg=t["panel_bg"], fg=t["text"])
        self.console.configure(bg=t["console_bg"], fg=t["console_fg"], insertbackground=t["console_fg"])
        self.console.tag_configure("muted", foreground="#9db2d4")
        self.console.tag_configure("good", foreground=t["success"])
        self.console.tag_configure("warn", foreground=t["warning"])
        self.console.tag_configure("bad", foreground=t["danger"])
        self.progress_canvas.configure(bg=t["panel_bg"])
        self.stage_canvas.configure(bg=t["panel_bg"])
        self.progress_canvas.itemconfig(self.progress_bar_bg, fill=t["primary_soft"])
        self.progress_canvas.itemconfig(self.progress_bar_fg, fill=t["primary"])
        self.stage_label.configure(bg=t["panel_bg"], fg=t["muted"])
        for btn in [self.btn_main, self.btn_review, self.btn_stop, self.btn_output, self.btn_latest, self.btn_logs, *self.platform_buttons]:
            btn.configure(bg=t["primary_soft"], fg=t["text"], activebackground=t["primary"], activeforeground="#ffffff")
        active_btn = self.btn_h1 if self.current_hospital == "yiwu_yicheng" else self.btn_h2
        inactive_btn = self.btn_h2 if self.current_hospital == "yiwu_yicheng" else self.btn_h1
        active_btn.configure(bg=t["primary"], fg="#ffffff", activebackground=t["primary_dark"], activeforeground="#ffffff")
        inactive_btn.configure(bg=t["primary_soft"], fg=t["text"], activebackground=t["primary"], activeforeground="#ffffff")
        self.toast.configure(bg=t["toast"], fg="#ffffff")

    def _show_toast(self, text: str):
        self.toast.configure(text=text)
        self.toast.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        self.root.after(2600, self.toast.place_forget)

    def _draw_stage_bar(self):
        t = self._theme()
        self.stage_canvas.delete("all")
        width = max(self.stage_canvas.winfo_width(), 100)
        step_gap = width / max(len(self.stage_steps), 1)
        for i, label in enumerate(self.stage_steps):
            x = step_gap * i + step_gap / 2
            color = t["primary"] if i <= self.stage_index else t["border"]
            text_color = t["text"] if i <= self.stage_index else t["muted"]
            if i < len(self.stage_steps) - 1:
                x2 = step_gap * (i + 1) + step_gap / 2
                self.stage_canvas.create_line(x + 18, 12, x2 - 18, 12, fill=color, width=3)
            self.stage_canvas.create_oval(x - 12, 0, x + 12, 24, fill=color, outline="")
            self.stage_canvas.create_text(x, 12, text=str(i + 1), fill="#ffffff", font=("Microsoft YaHei UI", 9, "bold"))
            self.stage_canvas.create_text(x, 31, text=label, fill=text_color, font=("Microsoft YaHei UI", 9))

    def _set_stage_by_line(self, stripped: str):
        if "长尾词" in stripped or "扩展长尾词" in stripped:
            self.current_stage = "长尾扩展"
            self.stage_index = 0
        elif "生成初稿" in stripped or "初稿完成" in stripped:
            self.current_stage = "首稿生成"
            self.stage_index = 1
        elif "去AI化" in stripped:
            self.current_stage = "去AI化"
            self.stage_index = 2
        elif "质量评分" in stripped or "重新评分" in stripped or "重试" in stripped:
            self.current_stage = "评分重写"
            self.stage_index = 3
        elif "已保存" in stripped or "[SAVE]" in stripped:
            self.current_stage = "保存完成"
            self.stage_index = 4
        self.stage_label.configure(text=f"当前阶段：{self.current_stage}")

    def _refresh_cfg_box(self):
        self.cfg_box.configure(state="normal")
        self.cfg_box.delete("1.0", "end")
        self.cfg_box.insert("1.0", self._build_cfg_text())
        self.cfg_box.configure(state="disabled")

    def switch_hospital(self, key: str):
        if self.process and self.process.poll() is None:
            messagebox.showinfo(APP_TITLE, "当前任务运行中，先停止后再切换医院。")
            return
        self.current_hospital = key
        self.hospital_text.set(HOSPITALS[key]["label"])
        self._refresh_cfg_box()
        self._apply_theme()
        self._append_line(f"已切换到 {HOSPITALS[key]['label']}", "good")

    def _append_line(self, text: str, tag: str = ""):
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
        subdirs = [os.path.join(output_root, name) for name in os.listdir(output_root) if os.path.isdir(os.path.join(output_root, name))]
        if subdirs:
            latest = max(subdirs, key=os.path.getmtime)
            os.startfile(latest)
        else:
            os.startfile(output_root)

    def _set_mode(self, mode: str):
        self.mode_text.set("审阅台模式" if mode == "review" else "主生成模式")

    def start_process(self, mode: str, platform_only: str = ""):
        if self.process and self.process.poll() is None:
            messagebox.showinfo(APP_TITLE, "当前已有任务在运行。")
            return
        script_map = {"main": self._main_py(), "review": self._review_py()}
        script = script_map[mode]
        if not os.path.exists(script):
            messagebox.showerror(APP_TITLE, f"未找到脚本：{script}")
            return
        self.process_mode = mode
        self.current_run_label = f"单平台模式：{platform_only}" if platform_only else "全量模式（12篇）"
        self.saved_count = 0
        self.error_count = 0
        self.progress_target = 3 if platform_only else self._read_config_int("BATCH_SIZE", 12)
        self.run_output_baseline_ts = datetime.now().timestamp()
        self.progress_value.set(0)
        self.progress_text.set("0%")
        self.current_stage = "长尾扩展"
        self.stage_index = 0
        self.stage_label.configure(text=f"当前阶段：{self.current_stage}")
        self.start_time = datetime.now()
        self.status_text.set("正在启动")
        self.meta_text.set(f"正在拉起任务进程...（{self.current_run_label}）")
        self.stats_text.set("已保存 0 篇 · 错误 0 条")
        self._set_mode(mode)
        self.btn_latest.configure(text="打开已生成文件夹")
        self._append_line("=" * 72, "muted")
        self._append_line(f"[{self.start_time.strftime('%H:%M:%S')}] 启动 {HOSPITALS[self.current_hospital]['label']} / {os.path.basename(script)} / {self.current_run_label}", "good")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        python_exec = pythonw if mode == "review" and os.path.exists(pythonw) else sys.executable
        launch_cmd = [python_exec, script]
        if mode == "main" and platform_only:
            launch_cmd += ["--platform", platform_only]

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
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()
        self.root.after(260, self._tick_runtime)

    def stop_process(self):
        if not self.process or self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            self._append_line("已发送停止指令。", "warn")
        except Exception as exc:
            self._append_line(f"停止失败：{exc}", "bad")

    def _read_output(self):
        try:
            if self.process.stdout:
                for line in self.process.stdout:
                    self.queue.put(("line", line.rstrip("\r\n")))
        finally:
            code = self.process.wait()
            self.queue.put(("done", code))

    def _count_generated_files(self) -> int:
        output_root = self._output_dir()
        if not os.path.exists(output_root):
            return 0
        latest_dir = output_root
        subdirs = [os.path.join(output_root, name) for name in os.listdir(output_root) if os.path.isdir(os.path.join(output_root, name))]
        if subdirs:
            latest_dir = max(subdirs, key=os.path.getmtime)
        count = 0
        for name in os.listdir(latest_dir):
            path = os.path.join(latest_dir, name)
            if name.lower().endswith('.txt') and os.path.isfile(path) and os.path.getmtime(path) >= self.run_output_baseline_ts:
                count += 1
        return count

    def _animate_progress(self):
        if self.process_mode == "main":
            actual_count = self._count_generated_files()
            if actual_count > self.saved_count:
                self.saved_count = actual_count
                pct = min(100, round(self.saved_count / max(self.progress_target, 1) * 100))
                self.progress_value.set(pct)
                self.stats_text.set(f"已保存 {self.saved_count} / {self.progress_target} 篇 · 错误 {self.error_count} 条")
        pct = float(self.progress_value.get())
        self.progress_text.set(f"{round(pct)}%")
        width = max(self.progress_canvas.winfo_width(), 10)
        self.progress_canvas.coords(self.progress_bar_bg, 0, 0, width, 16)
        self.progress_canvas.coords(self.progress_bar_fg, 0, 0, width * pct / 100.0, 16)
        self._draw_stage_bar()
        self.root.after(90, self._animate_progress)

    def _handle_line(self, line: str):
        stripped = line.strip()
        if "[ERR]" in stripped or "Traceback" in stripped or "失败" in stripped:
            tag = "bad"
            self.error_count += 1
        elif "[OK]" in stripped or "Running on http://127.0.0.1:5050" in stripped:
            tag = "good"
        else:
            tag = "muted"
        self._append_line(stripped if stripped else "", tag)
        self._set_stage_by_line(stripped)
        if "已保存" in stripped or "[SAVE]" in stripped:
            self.saved_count += 1
            pct = min(100, round(self.saved_count / max(self.progress_target, 1) * 100))
            self.progress_value.set(pct)
        if self.process_mode == "review" and "Running on http://127.0.0.1:5050" in stripped:
            self.status_text.set("审阅台运行中")
            self.meta_text.set("审阅台已启动，可直接在浏览器使用")
        elif self.process_mode == "main":
            self.status_text.set("正在生成")
        self.stats_text.set(f"已保存 {self.saved_count} 篇 · 错误 {self.error_count} 条")

    def _handle_done(self, code: int):
        elapsed = "-"
        if self.start_time:
            elapsed_sec = int((datetime.now() - self.start_time).total_seconds())
            minutes, seconds = divmod(elapsed_sec, 60)
            elapsed = f"{minutes}分{seconds:02d}秒"
        if code == 0:
            self.current_stage = "保存完成"
            self.stage_index = 4
            self.stage_label.configure(text=f"当前阶段：{self.current_stage}")
            self.status_text.set("运行完成")
            self.meta_text.set(f"{self.current_run_label}，任务已结束，用时 {elapsed}")
            self._append_line(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成", "good")
            self.btn_latest.configure(text="打开已生成文件夹 ★")
            self._show_toast("本轮文案已生成完成")
        else:
            self.status_text.set("运行中断")
            self.meta_text.set(f"{self.current_run_label}，任务异常退出，退出码 {code}，用时 {elapsed}")
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
        if not self.process or self.process.poll() is not None or not self.start_time:
            return
        elapsed_sec = int((datetime.now() - self.start_time).total_seconds())
        minutes, seconds = divmod(elapsed_sec, 60)
        if self.process_mode == "main":
            self.meta_text.set(f"{self.current_run_label}，生成中，已耗时 {minutes}分{seconds:02d}秒")
        elif self.process_mode == "review":
            self.meta_text.set(f"审阅台服务运行中，已耗时 {minutes}分{seconds:02d}秒")
        self.root.after(1000, self._tick_runtime)

    def _on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(APP_TITLE, "当前任务还在运行，关闭窗口会终止任务。确定关闭吗？"):
                return
            try:
                self.process.terminate()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
