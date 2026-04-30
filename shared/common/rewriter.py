import os
import random

from config import AUX_PROVIDER, GENERATOR_PROVIDER, REWRITE_PROVIDER
from modules.llm import require_llm_content
from project_paths import prompt_path

_VARIATION_STYLES = [
    "从个人经历角度重新表达",
    "从旁观者帮朋友查资料的角度表达",
    "用更平淡、不确定的语气表达",
    "用更口语化、随意的方式表达",
]

PROBLEM_TO_SEGMENT = {
    "ai_opening": "opening",
    "no_scene": "opening",
    "marketing": "opening",
    "no_hesitation": "opening",
    "low_info_density": "middle",
    "paired_structure": "middle",
    "no_detail": "middle",
    "ai_ending": "ending",
    "summary": "ending",
    "structured": "middle",
}


def _load(name: str) -> str:
    path = prompt_path("rewriter", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _rewrite_provider(default: str = None) -> str:
    if os.environ.get("X_GENERATION_MODE") == "quality":
        return REWRITE_PROVIDER or default or AUX_PROVIDER
    return default or AUX_PROVIDER


def rewrite_text(text: str) -> str:
    prompt = _load("rewrite.txt").replace("{text}", text)
    return require_llm_content(
        prompt,
        provider=_rewrite_provider(AUX_PROVIDER),
        empty_error="rewrite returned empty content",
        stage="rewrite_text",
    )


def restructure_text(text: str) -> str:
    prompt = _load("restructure.txt").replace("{text}", text)
    return require_llm_content(
        prompt,
        provider=_rewrite_provider(AUX_PROVIDER),
        empty_error="restructure returned empty content",
        stage="rewrite_restructure",
    )


def semantic_variation(text: str) -> str:
    style = random.choice(_VARIATION_STYLES)
    prompt = _load("variation.txt").replace("{text}", text).replace("{style}", style)
    return require_llm_content(
        prompt,
        provider=_rewrite_provider(AUX_PROVIDER),
        empty_error="variation returned empty content",
        stage="rewrite_variation",
    )


def apply_random_rewrite(text: str) -> str:
    fn = random.choice([rewrite_text, restructure_text, semantic_variation])
    return fn(text)


def rewrite_segment(segment_name: str, text: str, problems: list) -> str:
    prompt_file = f"segment_{segment_name}.txt"
    prompt = (
        _load(prompt_file)
        .replace("{text}", text)
        .replace("{problems}", "、".join(problems) or "整体 AI 感偏重")
    )
    result = require_llm_content(
        prompt,
        fast=False,
        provider=_rewrite_provider(GENERATOR_PROVIDER),
        empty_error=f"{segment_name} segment rewrite returned empty content",
        stage=f"rewrite_segment:{segment_name}",
    )
    return (result or text).strip()


def pick_target_segments(problems: list) -> list:
    targets = []
    for tag in problems:
        segment = PROBLEM_TO_SEGMENT.get(tag)
        if segment and segment not in targets:
            targets.append(segment)
    return targets or ["middle"]
