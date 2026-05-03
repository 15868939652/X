"""Industry knowledge base with keyword-indexed retrieval.

Loads structured medical domain data (hospitals, checkups, symptoms) and
supports keyword-based lookup for prompt augmentation.  Replaces the
hand-maintained ``industry/*.txt`` files with queryable JSON.
"""

import json
import os
import random
import re

_KB = None
_CACHE_PATH = None


def _resolve_path() -> str:
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "prompts", "common", "industry", "knowledge_base.json"),
        os.path.join(os.path.dirname(__file__), "prompts", "common", "industry", "knowledge_base.json"),
    ]
    for path in candidates:
        if os.path.exists(os.path.normpath(path)):
            return os.path.normpath(path)
    return os.path.normpath(candidates[0])


def load() -> dict:
    global _KB, _CACHE_PATH
    path = _resolve_path()
    if _KB is not None and _CACHE_PATH == path:
        return _KB
    try:
        with open(path, "r", encoding="utf-8") as f:
            _KB = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _KB = {}
    _CACHE_PATH = path
    return _KB


def _fuzzy_match(keyword: str, target: str) -> bool:
    """Check if keyword is a fuzzy substring of target (case-insensitive)."""
    kw = keyword.strip().lower()
    tg = target.strip().lower()
    if kw in tg or tg in kw:
        return True
    # Try matching each character of keyword in order within target
    pos = 0
    for ch in kw:
        pos = tg.find(ch, pos)
        if pos == -1:
            return False
        pos += 1
    return True


def search(category: str, keyword: str, n: int = 3) -> list[str]:
    """Search the knowledge base and return up to *n* formatted text items.

    *category* is one of ``"hospitals"``, ``"checkups"``, ``"symptoms"``.
    *keyword* is used to match the appropriate sub-category (department name,
    city name, hospital type, etc.).
    """
    kb = load()
    if category not in kb:
        return []

    data = kb[category]
    keyword = keyword.strip()

    if category == "hospitals":
        return _search_hospitals(data, keyword, n)
    elif category == "checkups":
        return _search_checkups(data, keyword, n)
    elif category == "symptoms":
        return _search_symptoms(data, keyword, n)
    return []


def _format_hospital(entry: dict) -> list[str]:
    """Format a single rich hospital entry into prompt-ready lines."""
    lines = [f"【{entry['name']}】"]
    lines.append(f"类型：{entry.get('type', '')}")
    lines.append(f"地址：{entry.get('address', '')}")
    lines.append(f"成立：{entry.get('founded', '')}")
    if entry.get("overview"):
        lines.append(f"概况：{entry['overview']}")
    # key departments
    kd = entry.get("key_departments", [])
    if kd:
        lines.append("重点科室：")
        for d in kd:
            lines.append(f"  - {d['name']}：{d['feature']}")
    # specialists
    sp = entry.get("specialists", [])
    if sp:
        lines.append("专家团队：")
        for s in sp:
            base = f"  - {s['name']}（{s['title']}）：{s['specialty']}"
            if s.get("highlight"):
                base += f"（{s['highlight']}）"
            lines.append(base)
    # features
    feats = entry.get("features", [])
    if feats:
        lines.append("特色：" + "；".join(feats))
    # full department list
    depts = entry.get("departments", [])
    if depts:
        lines.append("科室列表：" + "、".join(depts))
    return lines


def _search_hospitals(data: dict, keyword: str, n: int) -> list[str]:
    results = []

    # 1) Local hospitals: match by city name OR hospital name
    local = data.get("local", {})
    matched_entries = []
    for city, entries in local.items():
        for entry in entries:
            if _fuzzy_match(keyword, entry["name"]):
                matched_entries.append(entry)
        if not matched_entries and _fuzzy_match(keyword, city):
            matched_entries = list(entries)

    for entry in matched_entries:
        results.extend(_format_hospital(entry))

    # 2) Hospital type matching 公立/私立
    if not matched_entries:
        types = data.get("types", {})
        for ownership, subtypes in types.items():
            if keyword in ownership or ownership in keyword:
                for subtype, desc in subtypes.items():
                    results.append(f"- {subtype}（{ownership}）：{desc}")
                break

    # Bail early if nothing matched
    if not results:
        return []

    # 3) Generic descriptions — only when a match exists
    descs = data.get("descriptions", {})
    sampled = []
    for aspect in ("环境", "服务", "流程"):
        entries = descs.get(aspect, [])
        if entries:
            sampled.append(random.choice(entries))
    if sampled:
        results.append("就诊体验：" + "；".join(sampled))

    # 4) Visit process — only when a match exists
    processes = data.get("visit_process", [])
    if processes:
        results.append("典型流程：" + random.choice(processes))

    return results[:n]


def _search_checkups(data: dict, keyword: str, n: int) -> list[str]:
    results = []
    for dept, items in data.items():
        if _fuzzy_match(keyword, dept):
            results.append(f"【{dept}相关检查】")
            for item in items:
                results.append(f"- {item['name']}：{item['desc']}，参考费用 {item['cost']} 元")
            break

    # If no department match, try matching individual item names
    if not results:
        for dept, items in data.items():
            for item in items:
                if _fuzzy_match(keyword, item["name"]):
                    results.append(f"- {item['name']}（{dept}）：{item['desc']}，参考费用 {item['cost']} 元")
    return results[:max(n, len(results))]


def _search_symptoms(data: dict, keyword: str, n: int) -> list[str]:
    results = []
    for dept, entries in data.items():
        if _fuzzy_match(keyword, dept):
            results.append(f"【{dept}常见主诉（参考，勿直接复制）】")
            results.extend(f"- {s}" for s in random.sample(entries, min(n, len(entries))))
            break
    return results[:n + 1]


def expand(text: str) -> str:
    """Replace ``{KB:category:keyword}`` and ``{KB:category:keyword:n}``
    placeholders with knowledge base content.

    Example: ``{KB:checkups:妇科:3}`` → top 3 checkup items for 妇科.
    """
    def _replace(match):
        category = match.group(1)
        keyword = match.group(2)
        n_str = match.group(3)
        n = int(n_str) if n_str else 3
        items = search(category, keyword, n)
        if not items:
            return match.group(0)
        return "\n".join(items)

    return re.sub(r"\{KB:(hospitals|checkups|symptoms):([^:}]+)(?::(\d+))?\}", _replace, text)
