from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
_SHARED_PROMPTS = WORKSPACE_ROOT / "shared" / "prompts" / "common"


def project_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath(*parts))


def prompt_path(*parts: str) -> str:
    local = PROJECT_ROOT / "prompts" / Path(*parts)
    if local.exists():
        return str(local)
    shared = _SHARED_PROMPTS / Path(*parts)
    if shared.exists():
        return str(shared)
    return str(local)


def data_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath("data", *parts))
