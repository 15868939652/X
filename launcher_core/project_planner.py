from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from shared.common.task_planner import build_task_specs


def load_project_profile(project_dir: str | Path, project_key: str) -> dict:
    profile_path = Path(project_dir) / "profiles" / f"{project_key}.py"
    spec = importlib.util.spec_from_file_location(f"launcher_profile_{project_key}", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载项目配置：{profile_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.PROFILE)


def build_project_task_specs(project_dir: str | Path, project_key: str, count: int, platforms: list[str]) -> list[dict]:
    profile = load_project_profile(project_dir, project_key)
    keyword_path = Path(project_dir) / profile["keyword_file"]
    return build_task_specs(profile, keyword_path, platforms, count)


def save_plan(plan_path: str | Path, tasks: list[dict], metadata: dict | None = None) -> str:
    payload = {
        "tasks": tasks,
        "metadata": metadata or {},
    }
    path = Path(plan_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
