"""
规则评分层：不调 LLM，靠正则和计数快速拦截低级问题。

输出与 LLM 评分相同形状的 dict：
    {"score": int, "problems": [tag...], "reason": str}

与 LLM 评分按 0.3 / 0.7 加权合并，详见 modules/scorer.py。
"""

import re
from typing import List, Dict

# ---------- 硬红线：命中直接拉低分数 ----------
HARD_BANNED = [
    "强烈推荐", "首选", "最好去", "必去", "希望帮到你",
    "希望对大家有帮助", "感谢阅读", "欢迎留言",
    "随着", "近年来", "越来越多人", "相信大家都知道",
]

# ---------- 总结类短语：AI 感最强的尾巴 ----------
SUMMARY_PHRASES = [
    "总的来说", "总而言之", "综上所述", "总之", "总体来看",
    "总结一下", "总结来说", "整体而言",
]

# ---------- AI 常见对称句式 ----------
PAIRED_PATTERNS = [
    r"不仅[^，。！？\n]{1,30}(而且|也|还)",
    r"一方面[^，。！？\n]{1,30}(另一方面|一方面)",
    r"既[^，。！？\n]{1,30}又",
]

# ---------- 真实感锚点：有一点就加分 ----------
HESITATION_MARKERS = [
    "感觉", "好像", "不太确定", "不确定", "大概", "可能",
    "有点", "还在", "刚了解", "仅供参考", "纠结",
]

# ---------- 按写作模式的字数要求（优先用这个，没有再 fallback 到平台） ----------
MODE_LENGTH = {
    "info":       (400, 900),
    "light_exp":  (400, 900),
    "other_exp":  (400, 900),
    "exp":        (200, 500),
    "hesitate":   (150, 350),
    "short":      (100, 250),
}

# ---------- 平台字数要求（fallback） ----------
PLATFORM_LENGTH = {
    "toutiao":   (200, 800),
    "zhihu":     (300, 900),
    "sohu":      (400, 1500),
    "baijiahao": (300, 1200),
}


def _count_hits(text: str, items) -> int:
    return sum(text.count(w) for w in items)


def _count_regex(text: str, patterns) -> int:
    total = 0
    for p in patterns:
        total += len(re.findall(p, text))
    return total


def _repeat_ratio(text: str) -> float:
    """粗略估计重复度：按 15 字窗口切 shingles 看唯一率。值越高 = 重复越多。"""
    text = re.sub(r"\s+", "", text)
    if len(text) < 60:
        return 0.0
    win = 15
    shingles = [text[i:i + win] for i in range(0, len(text) - win, 5)]
    if not shingles:
        return 0.0
    return 1 - len(set(shingles)) / len(shingles)


def rule_score(text: str, platform: str = "", mode: str = "") -> Dict:
    problems: List[str] = []
    reasons: List[str] = []
    score = 100

    length = len(text)
    if mode and mode in MODE_LENGTH:
        lo, hi = MODE_LENGTH[mode]
    else:
        lo, hi = PLATFORM_LENGTH.get(platform, (200, 1500))
    if length < lo:
        score -= 20
        problems.append("length_too_short")
        reasons.append(f"字数 {length} < {lo}")
    elif length > hi:
        score -= 10
        problems.append("length_too_long")
        reasons.append(f"字数 {length} > {hi}")

    banned_hits = _count_hits(text, HARD_BANNED)
    if banned_hits > 0:
        score -= 15 * banned_hits
        problems.append("banned_words")
        reasons.append(f"命中禁止词 {banned_hits} 次")

    summary_hits = _count_hits(text, SUMMARY_PHRASES)
    if summary_hits > 0:
        score -= 10 * summary_hits
        problems.append("summary_phrase")
        reasons.append(f"总结类短语 {summary_hits} 次")

    paired_hits = _count_regex(text, PAIRED_PATTERNS)
    if paired_hits >= 2:
        score -= 8 * (paired_hits - 1)
        problems.append("paired_structure")
        reasons.append(f"对称句式 {paired_hits} 次")

    rep = _repeat_ratio(text)
    if rep > 0.25:
        score -= 15
        problems.append("repetition_high")
        reasons.append(f"重复度 {rep:.2f}")

    # exp 是已完成就诊的回顾，不要求纠结表达
    # hesitate/short 篇幅短，开放提问或简短口语也允许没有显式犹豫词
    if mode not in ("exp", "short") and _count_hits(text, HESITATION_MARKERS) == 0:
        score -= 5
        problems.append("no_hesitation")
        reasons.append("缺少纠结/不确定表达")

    # 信息密度：exp/hesitate/short 不要求多方信息对比，跳过此项
    if mode not in ("exp", "hesitate", "short"):
        has_number = bool(re.search(r"\d", text))
        has_contrast = any(w in text for w in ["有人说", "也有", "网上", "论坛", "不过", "但是"])
        if not has_number and not has_contrast:
            score -= 5
            problems.append("low_info_density")
            reasons.append("无具体数字且无信息对比")

    score = max(0, min(100, score))
    return {
        "score": score,
        "problems": problems,
        "reason": "；".join(reasons) or "无规则扣分项",
        "length": length,
        "repetition": round(rep, 3),
    }
