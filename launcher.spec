# -*- mode: python ; coding: utf-8 -*-
"""
X-Launcher PyInstaller 构建 — CustomTkinter 版
构建命令: pyinstaller launcher.spec
"""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = []
IGNORED_DIRS = {"__pycache__", "output", "logs", ".git"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

# 所有提示词文件
# Bundle shared/ directory (excluding __pycache__)
for root, dirs, files in os.walk("shared"):
    dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
    for f in files:
        if os.path.splitext(f)[1].lower() in IGNORED_SUFFIXES:
            continue
        datas.append((os.path.join(root, f), root))

# Bundle project files
for project in ["yiwu_yicheng", "yiwu_weichuang"]:
    base = os.path.join("projects", project)
    # Bundle all project files (py, txt, xlsx, json, jsonl)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() in IGNORED_SUFFIXES:
                continue
            src = os.path.join(root, f)
            dst = root  # keep directory structure intact
            datas.append((src, dst))

datas += collect_data_files("customtkinter")

base_prefix = getattr(sys, "base_prefix", sys.prefix)
tcl_root = os.path.join(base_prefix, "tcl")
for runtime_dir in ("tcl8.6", "tk8.6"):
    src_dir = os.path.join(tcl_root, runtime_dir)
    if os.path.isdir(src_dir):
        for root, dirs, files in os.walk(src_dir):
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(runtime_dir, os.path.relpath(root, src_dir))
                datas.append((src, dst))

hiddenimports = [
    "pandas",
    "numpy",
    "openpyxl",
    "openai",
    "httpx",
    "flask",
    "werkzeug",
    "jinja2",
    "markupsafe",
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "customtkinter",
    "rich.console",
    "rich.panel",
]
# customtkinter 资源较特殊，保留其子模块自动收集
hiddenimports += collect_submodules("customtkinter")

a = Analysis(
    ["launcher_gui.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "matplotlib.pyplot",
        "scipy",
        "PIL",
        "pytest",
        "pandas.tests",
        "numpy.tests",
        "pyarrow",
        "numba",
        "sklearn",
        "IPython",
        "jupyter",
        "dotenv",
        "flask.cli",
        "click.testing",
        "setuptools",
        "pygments",
        "markdown_it",
        "mdurl",
        "rich.markdown",
        "rich.pretty",
        "rich.syntax",
        "rich.traceback",
        "attr",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="X-Launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
