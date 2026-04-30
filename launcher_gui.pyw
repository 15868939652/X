from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from launcher_core.app import LauncherApp


def _source_root() -> Path:
    return Path(__file__).resolve().parent


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", _source_root()))


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_root()


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


def _ensure_runtime_layout(project_key: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    bundle_root = _bundle_root()
    runtime_root = _runtime_root()
    _copy_tree(bundle_root / "shared", runtime_root / "shared")
    _copy_tree(bundle_root / "projects" / project_key, runtime_root / "projects" / project_key)


def _project_dir(project_key: str) -> Path:
    if getattr(sys, "frozen", False):
        return _runtime_root() / "projects" / project_key
    return _bundle_root() / "projects" / project_key


def _shared_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _runtime_root() / "shared"
    return _bundle_root() / "shared"


def _parse_worker_args(argv: list[str]) -> dict:
    options = {
        "project_key": "yiwu_weichuang",
    }
    i = 1
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            options["project_key"] = argv[i + 1].strip()
            i += 2
        else:
            i += 1
    return options


def _clear_project_modules() -> None:
    project_prefixes = (
        "config",
        "modules",
        "profiles",
        "pathing",
        "project_paths",
        "bootstrap_shared",
        "main",
        "review_ui",
        "analyze",
    )
    for name in list(sys.modules):
        for prefix in project_prefixes:
            if name == prefix or name.startswith(prefix + "."):
                del sys.modules[name]
                break


def _normalize_worker_paths(argv: list[str], base_dir: Path) -> list[str]:
    normalized = list(argv)
    for flag in ("--plan", "--pause-file"):
        i = 1
        while i < len(normalized):
            if normalized[i] == flag and i + 1 < len(normalized):
                candidate = Path(normalized[i + 1])
                if not candidate.is_absolute():
                    normalized[i + 1] = str((base_dir / candidate).resolve())
                i += 2
            else:
                i += 1
    return normalized


def _run_worker() -> None:
    original_cwd = Path.cwd()
    sys.argv = _normalize_worker_paths(sys.argv, original_cwd)
    options = _parse_worker_args(sys.argv)
    _ensure_runtime_layout(options["project_key"])
    project_dir = _project_dir(options["project_key"])
    shared_dir = _shared_dir()

    if not project_dir.exists():
        raise RuntimeError(f"Project directory not found: {project_dir}")

    _clear_project_modules()

    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    if str(shared_dir) not in sys.path:
        sys.path.append(str(shared_dir))
    os.chdir(project_dir)

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    import bootstrap_shared  # noqa: F401
    import main

    main.cli()


def main() -> None:
    if "--worker" in sys.argv[1:]:
        _run_worker()
        return
    if getattr(sys, "frozen", False):
        _ensure_runtime_layout("yiwu_yicheng")
        _ensure_runtime_layout("yiwu_weichuang")
    LauncherApp().run()


if __name__ == "__main__":
    main()
