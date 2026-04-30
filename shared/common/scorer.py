"""
评分器：LLM 评分 * 0.5 + 规则评分 * 0.5
"""

import json
import re
from typing import Dict

import os

from config import AUX_PROVIDER, SCORE_PROVIDER, SCORER_USE_PRO
from modules.llm import call_llm_result
from modules.rule_scorer import rule_score
from pathing import shared_prompt_path

W_LLM = 0.5
W_RULE = 0.5
SCORER_ERROR_TAG = "scorer_error"


def _load_prompt() -> str:
    path = shared_prompt_path("scorer.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _normalize_score(value) -> int:
    score = int(value)
    return max(0, min(100, score))


def _parse_json_payload(result: str) -> Dict | None:
    result = (result or "").strip()
    if not result:
        return None
    match = re.search(r"\{.*\}", result, re.DOTALL)
    if not match:
        return None
    payload = json.loads(match.group(0))
    score = _normalize_score(payload["score"])
    problems = payload.get("problems") or []
    if isinstance(problems, str):
        problems = [problems]
    problems = [str(item).strip() for item in problems if str(item).strip()]
    reason = str(payload.get("reason") or "").strip()
    return {
        "score": score,
        "problems": problems,
        "reason": reason,
        "raw": result[:800],
        "format": "json",
    }


def _parse_legacy_payload(result: str) -> Dict | None:
    if not result:
        return None
    try:
        match = re.search(r"得分[:：]\s*(\d+)", result)
        if not match:
            return None
        score = _normalize_score(match.group(1))
    except Exception:
        return None

    problems = []
    match = re.search(r"问题标签[:：]\s*([^\n]+)", result)
    if match:
        raw = match.group(1).strip()
        if raw and raw.lower() not in ("none", "无"):
            problems = [item.strip() for item in re.split(r"[，,、]", raw) if item.strip()]

    reason = ""
    match = re.search(r"扣分说明[:：]\s*([^\n]+)", result)
    if match:
        reason = match.group(1).strip()
        if reason == "无":
            reason = ""

    return {
        "score": score,
        "problems": problems,
        "reason": reason,
        "raw": result[:800],
        "format": "legacy",
        "warning": "scorer returned legacy format",
    }


def _scorer_error(reason: str, raw: str = "") -> Dict:
    return {
        "score": -1,
        "problems": [SCORER_ERROR_TAG],
        "reason": reason,
        "raw": raw[:800],
        "format": "error",
        "status": "error",
    }


def _parse_llm(result: str) -> Dict:
    try:
        payload = _parse_json_payload(result)
        if payload:
            payload["status"] = "ok"
            return payload
    except Exception as exc:
        return _scorer_error(f"评分 JSON 解析失败: {exc}", result)

    legacy = _parse_legacy_payload(result)
    if legacy:
        legacy["status"] = "ok"
        print("[WARN] scorer returned legacy format; please update prompt/output alignment.")
        return legacy

    return _scorer_error("评分输出无法解析", result)


def score_llm(text: str) -> Dict:
    prompt = _load_prompt().replace("{text}", text)
    provider = SCORE_PROVIDER if os.environ.get("X_GENERATION_MODE") == "quality" else AUX_PROVIDER
    retries = 0 if os.environ.get("X_GENERATION_MODE") == "quality" else None
    llm_result = call_llm_result(prompt, fast=not SCORER_USE_PRO, provider=provider, retries=retries, stage="score")
    if llm_result.failed:
        return _scorer_error(f"评分模型调用失败: {llm_result.error}", "")
    if llm_result.empty:
        return _scorer_error("评分模型返回空内容", "")

    parsed = _parse_llm(llm_result.content)
    parsed["attempts"] = llm_result.attempts
    parsed["provider"] = llm_result.provider
    parsed["model"] = llm_result.model
    return parsed


def score_article_detailed(text: str, platform: str = "", mode: str = "") -> Dict:
    llm = score_llm(text)
    rule = rule_score(text, platform=platform, mode=mode)

    if llm["score"] < 0:
        final = -1
    elif llm["score"] <= 50:
        final = llm["score"]
    else:
        final = round(llm["score"] * W_LLM + rule["score"] * W_RULE)

    merged_problems = list(dict.fromkeys(llm["problems"] + rule["problems"]))
    reason_parts = []
    if llm["reason"]:
        reason_parts.append(f"[LLM] {llm['reason']}")
    if llm.get("warning"):
        reason_parts.append(f"[WARN] {llm['warning']}")
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
    return score_article_detailed(text, platform, mode)["score"]
