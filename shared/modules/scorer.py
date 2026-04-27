"""
评分器：LLM 评分（硬约束 prompt）× 0.7 + 规则评分 × 0.3

返回结构：
    {
        "score": int,              # 加权后的最终分
        "problems": [tag...],      # 合并后的问题标签
        "reason": str,             # 人类可读的扣分说明
        "llm": {score, problems, reason},
        "rule": {score, problems, reason, length, repetition},
    }
"""

import os
import re
from typing import Dict

from config import SCORER_USE_PRO, AUX_PROVIDER
from modules.llm import call_llm
from modules.rule_scorer import rule_score

# LLM/规则权重（rule 层已被证明能抓到 lite 漏掉的真问题，权重对半）
W_LLM = 0.5
W_RULE = 0.5


def _load_prompt() -> str:
    path = os.path.join("prompts", "scorer.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_llm(result: str) -> Dict:
    """从 v3.0 硬约束 prompt 的返回里抽出结构化结果。"""
    try:
        m = re.search(r"得分[:：]\s*(\d+)", result)
        score = int(m.group(1)) if m else 60
    except Exception:
        score = 60
    score = max(0, min(100, score))

    problems = []
    m = re.search(r"问题标签[:：]\s*([^\n]+)", result)
    if m:
        raw = m.group(1).strip()
        if raw and raw.lower() not in ("none", "无"):
            problems = [t.strip() for t in re.split(r"[，,、]", raw) if t.strip()]

    reason = ""
    m = re.search(r"扣分说明[:：]\s*([^\n]+)", result)
    if m:
        reason = m.group(1).strip()
        if reason in ("无",):
            reason = ""

    return {"score": score, "problems": problems, "reason": reason, "raw": result[:800]}


def score_llm(text: str) -> Dict:
    prompt = _load_prompt().replace("{text}", text)
    result = call_llm(prompt, fast=not SCORER_USE_PRO, provider=AUX_PROVIDER)
    return _parse_llm(result)


def score_article_detailed(text: str, platform: str = "", mode: str = "") -> Dict:
    """baseline / generator 使用。返回完整的评分 dict。"""
    llm = score_llm(text)
    rule = rule_score(text, platform=platform, mode=mode)

    # 红线触发时（LLM ≤ 50）不做加权，直接用 LLM 分
    # 否则规则分会把红线文章从 40 救回到 70 刚好压线通过
    if llm["score"] <= 50:
        final = llm["score"]
    else:
        final = round(llm["score"] * W_LLM + rule["score"] * W_RULE)

    merged_problems = list(dict.fromkeys(llm["problems"] + rule["problems"]))
    reason_parts = []
    if llm["reason"]:
        reason_parts.append(f"[LLM] {llm['reason']}")
    if rule["reason"] and rule["reason"] != "无规则扣分项":
        reason_parts.append(f"[规则] {rule['reason']}")

    return {
        "score": final,
        "problems": merged_problems,
        "reason": " | ".join(reason_parts) or "无扣分",
        "llm": llm,
        "rule": rule,
    }


def score_article(text: str, platform: str = "", mode: str = "") -> int:
    """兼容旧接口：只返回分数。"""
    return score_article_detailed(text, platform, mode)["score"]
