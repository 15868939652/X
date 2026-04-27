import os
import shutil
from pathlib import Path

ROOT = Path(r"c:\Users\Administrator\Desktop\yicheng")
PROJECTS = ROOT / "projects"
YICHENG = PROJECTS / "yiwu_yicheng"
WEICHUANG = PROJECTS / "yiwu_weichuang"

MOVE_ITEMS = [
    "analyze.py",
    "config.py",
    "data",
    "logs",
    "main.py",
    "modules",
    "output",
    "profiles",
    "prompts",
    "review_ui.py",
    "update_prompt.py",
]

PROJECTS.mkdir(exist_ok=True)
YICHENG.mkdir(exist_ok=True)

for name in MOVE_ITEMS:
    src = ROOT / name
    dst = YICHENG / name
    if src.exists() and not dst.exists():
        shutil.move(str(src), str(dst))

if not WEICHUANG.exists():
    shutil.copytree(YICHENG, WEICHUANG)

# 微创医院最小定制：品牌与 profile
cfg = WEICHUANG / "config.py"
text = cfg.read_text(encoding="utf-8")
text = text.replace('ACTIVE_PROFILE = "yiwu_yicheng"', 'ACTIVE_PROFILE = "yiwu_weichuang"')
text = text.replace('BRAND = "义乌义城医院"', 'BRAND = "义乌微创医院"')
cfg.write_text(text, encoding="utf-8")
