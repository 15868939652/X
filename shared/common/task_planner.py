import random
from pathlib import Path

import pandas as pd


def classify_keyword(keyword: str, department_keywords: dict) -> str:
    keyword = str(keyword).lower()
    for department, words in (department_keywords or {}).items():
        if any(word in keyword for word in words):
            return department
    return "常规体检"


def build_keyword_pool(df: pd.DataFrame, keyword_col: str, profile: dict, task_total: int) -> list[str]:
    departments = profile.get("departments", {})
    if "科室" not in df.columns:
        df["科室"] = df[keyword_col].apply(lambda kw: classify_keyword(kw, profile.get("department_keywords", {})))

    picked: list[str] = []
    for department, weight in departments.items():
        keywords = df[df["科室"] == department][keyword_col].dropna().tolist()
        random.shuffle(keywords)
        target = max(1, int(task_total * weight))
        if keywords and len(keywords) < target:
            while len(keywords) < target:
                keywords.extend(keywords[:target - len(keywords)])
        picked.extend(keywords[:target])

    if not picked:
        picked = df[keyword_col].dropna().tolist()

    while len(picked) < task_total and picked:
        picked.extend(picked[:task_total - len(picked)])
    picked = picked[:task_total]
    random.shuffle(picked)
    return picked


def load_keyword_dataframe(keyword_path: str | Path) -> tuple[pd.DataFrame, str]:
    df = pd.read_excel(keyword_path)
    keyword_col = "keyword" if "keyword" in df.columns else df.columns[0]
    df[keyword_col] = df[keyword_col].astype(str).str.strip()
    df = df[df[keyword_col] != ""]
    df = df.drop_duplicates(subset=[keyword_col]).reset_index(drop=True)
    return df, keyword_col


def build_task_specs(profile: dict, keyword_path: str | Path, platforms: list[str], task_total: int) -> list[dict]:
    df, keyword_col = load_keyword_dataframe(keyword_path)
    selected_kw = build_keyword_pool(df, keyword_col, profile, task_total)

    if not selected_kw:
        return []

    while len(selected_kw) < task_total:
        selected_kw.extend(selected_kw[:task_total - len(selected_kw)])
    selected_kw = selected_kw[:task_total]

    platform_slots = []
    base_count = task_total // len(platforms)
    remainder = task_total % len(platforms)
    for idx, platform in enumerate(platforms):
        platform_total = base_count + (1 if idx < remainder else 0)
        for platform_index in range(1, platform_total + 1):
            platform_slots.append((platform, platform_index))

    random.shuffle(platform_slots)
    random.shuffle(selected_kw)

    return [
        {
            "task_id": task_id,
            "base_keyword": keyword,
            "platform": platform,
            "platform_index": platform_index,
        }
        for task_id, ((platform, platform_index), keyword) in enumerate(zip(platform_slots, selected_kw), start=1)
    ]
