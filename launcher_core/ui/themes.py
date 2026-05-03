"""Color constants and theme management extracted from app.py."""

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

# Re-export for convenience
ACCENT_COLORS = {key: cfg["accent"] for key, cfg in PROJECTS.items()}
ACCENT_DEEP = {key: cfg["accent_deep"] for key, cfg in PROJECTS.items()}
ACCENT_SOFT = {key: cfg["accent_soft"] for key, cfg in PROJECTS.items()}


def apply_theme(app) -> None:
    cfg = app._cfg()
    accent = cfg["accent"]
    accent_deep = cfg["accent_deep"]
    accent_soft = cfg["accent_soft"]
    app.brand_badge.configure(fg_color=accent)
    app.main_btn.configure(fg_color=accent, hover_color=accent_deep, text_color="#FFFFFF")
    for btn in (
        app.stop_btn,
        app.platform_all_btn,
        app.btn_latest_dir,
        app.btn_txt_dir,
        app.btn_txt_file,
        app.task_retry_btn,
        app.task_copy_btn,
        app.task_export_btn,
        app.task_delete_btn,
        *app.single_platform_buttons.values(),
    ):
        btn.configure(fg_color=accent_soft, hover_color=accent_soft, text_color=accent_deep, border_width=1, border_color=accent)
    app.progress_bar.configure(progress_color=accent)
    app.batch_state_chip.configure(fg_color=accent_soft, text_color=accent_deep)
