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

# 所有提示词文件
# Bundle shared/ directory (excluding __pycache__)
for root, dirs, files in os.walk("shared"):
    if "__pycache__" in root:
        continue
    for f in files:
        datas.append((os.path.join(root, f), root))

# Bundle project files
for project in ["yiwu_yicheng", "yiwu_weichuang"]:
    base = os.path.join("projects", project)
    # Bundle all project files (py, txt, xlsx, json, jsonl)
    for root, dirs, files in os.walk(base):
        if "__pycache__" in root:
            continue
        for f in files:
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
    "pandas", "numpy", "openpyxl",
    "openai", "httpx",
    "flask", "werkzeug", "jinja2", "markupsafe",
    "tkinter", "tkinter.ttk", "tkinter.messagebox",
    "customtkinter",
]
# 递归收集大型库的所有子模块，避免遗漏
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("rich")
hiddenimports += collect_submodules("pandas")

a = Analysis(
    ["launcher_gui.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "PIL", "pytest"],
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
