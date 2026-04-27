import os
import random
from config import AUX_PROVIDER, GENERATOR_PROVIDER
from project_paths import prompt_path
from modules.llm import call_llm

_VARIATION_STYLES = [
    "从个人经历角度重新表达",
    "从旁观者/帮朋友查资料的角度表达",
    "用更平淡、不确定的语气表达",
    "用更口语化、随意的方式表达",
]

PROBLEM_TO_SEGMENT = {
    "ai_opening":        "opening",
    "no_scene":          "opening",
    "marketing":         "opening",
    "no_hesitation":     "opening",
    "low_info_density":  "middle",
    "paired_structure":  "middle",
    "no_detail":         "middle",
    "ai_ending":         "ending",
    "summary":           "ending",
    "structured":        "middle",
}


def _load(name: str) -> str:
    path = prompt_path("rewriter", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def rewrite_text(text: str) -> str:
    prompt = _load("rewrite.txt").replace("{text}", text)
    return call_llm(prompt, provider=AUX_PROVIDER)


def restructure_text(text: str) -> str:
    prompt = _load("restructure.txt").replace("{text}", text)
    return call_llm(prompt, provider=AUX_PROVIDER)


def semantic_variation(text: str) -> str:
    style = random.choice(_VARIATION_STYLES)
    prompt = _load("variation.txt").replace("{text}", text).replace("{style}", style)
    return call_llm(prompt, provider=AUX_PROVIDER)


def apply_random_rewrite(text: str) -> str:
    fn = random.choice([rewrite_text, restructure_text, semantic_variation])
    return fn(text)


# ========================= 段落级局部改写 =========================

def rewrite_segment(segment_name: str, text: str, problems: list) -> str:
    """
    只改某一段。segment_name ∈ {opening, middle, ending}。
    用生成层主模型保证改写质量。
    """
    prompt_file = f"segment_{segment_name}.txt"
    prompt = (
        _load(prompt_file)
        .replace("{text}", text)
        .replace("{problems}", "、".join(problems) or "整体 AI 感偏重")
    )
    result = call_llm(prompt, fast=False, provider=GENERATOR_PROVIDER)
    return (result or text).strip()


def pick_target_segments(problems: list) -> list:
    """根据问题标签决定要改哪些段。无匹配则返回 ['middle'] 保底。"""
    targets = []
    for tag in problems:
        seg = PROBLEM_TO_SEGMENT.get(tag)
        if seg and seg not in targets:
            targets.append(seg)
    return targets or ["middle"]
