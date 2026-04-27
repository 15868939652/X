import os
import random
from modules.llm import call_llm

_STYLES = [
    "疑问式",
    "经历分享式",
    "纠结式",
    "信息查询式",
    "隐晦求助式",
]


def _load_prompt() -> str:
    path = os.path.join("prompts", "title.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def generate_title(keyword: str) -> str:
    style = random.choice(_STYLES)
    prompt = (
        _load_prompt()
        .replace("{keyword}", keyword)
        .replace("{style}", style)
    )
    return call_llm(prompt)
