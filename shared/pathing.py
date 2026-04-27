import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent


def workspace_root() -> Path:
    return project_root().parent


def shared_root() -> Path:
    return workspace_root() / "shared"


def shared_prompt_path(*parts: str) -> str:
    return str(shared_root().joinpath("prompts", *parts))
