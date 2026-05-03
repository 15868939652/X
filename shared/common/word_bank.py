import json
import os
import random
import re

_WORD_BANKS = None
_CACHE_PATH = None


def _resolve_path() -> str:
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "prompts", "common", "word_banks.json"),
        os.path.join(os.path.dirname(__file__), "prompts", "common", "word_banks.json"),
    ]
    for path in candidates:
        if os.path.exists(os.path.normpath(path)):
            return os.path.normpath(path)
    return os.path.normpath(candidates[0])


def _load() -> dict:
    global _WORD_BANKS, _CACHE_PATH
    path = _resolve_path()
    if _WORD_BANKS is not None and _CACHE_PATH == path:
        return _WORD_BANKS
    try:
        with open(path, "r", encoding="utf-8") as f:
            _WORD_BANKS = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _WORD_BANKS = {}
    _CACHE_PATH = path
    return _WORD_BANKS


def sample(category: str, n: int = None) -> list:
    banks = _load()
    entries = banks.get(category, [])
    if not entries:
        return []
    if n is None:
        return list(entries)
    return random.sample(entries, min(n, len(entries)))


def expand(text: str) -> str:
    def _replace(match):
        category = match.group(1)
        fmt = match.group(2) or "inline"
        n_str = match.group(3)
        n = int(n_str) if n_str else None
        entries = sample(category, n)
        if not entries:
            return match.group(0)
        if fmt == "bullets":
            return "\n".join(f"- {e}" for e in entries)
        return "、".join(entries)

    return re.sub(r"\{WORD_BANK:(\w+)(?::(bullets|inline))?(?::(\d+))?\}", _replace, text)
