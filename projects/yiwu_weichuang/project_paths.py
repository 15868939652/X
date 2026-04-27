from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def project_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath(*parts))


def prompt_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath("prompts", *parts))


def data_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath("data", *parts))
