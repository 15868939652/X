import os

from config import ANTI_AI_PROVIDER, AUX_PROVIDER
from modules.llm import require_llm_content
from project_paths import prompt_path


def _load(name: str) -> str:
    path = prompt_path("anti_ai", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def anti_ai_pipeline(text: str) -> str:
    prompt = _load("combined.txt").replace("{text}", text)
    provider = ANTI_AI_PROVIDER if os.environ.get("X_GENERATION_MODE") == "quality" else AUX_PROVIDER
    return require_llm_content(
        prompt,
        fast=True,
        provider=provider,
        empty_error="anti-ai returned empty content",
        stage="anti_ai",
    )
