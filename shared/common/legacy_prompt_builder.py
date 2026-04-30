import os
import random
import re
from datetime import datetime

from config import BRAND, DRAFT_PROVIDER, GENERATOR_PROVIDER, MAX_RETRY, MIN_SCORE, PLATFORM_MIN_SCORE
from modules.anti_ai import anti_ai_pipeline
from modules.llm import call_llm_result
from modules.profile_loader import get_active_profile, get_other_brand_aliases
from modules.progress import show_done, show_params, show_retry, show_score, step
from modules.randomizer import random_profile, random_style, random_trigger
from modules.rewriter import apply_random_rewrite, pick_target_segments, rewrite_segment
from modules.rule_scorer import rule_score
from modules.scorer import score_article_detailed
from common.prompt_rules import (
    FULL_BODY_SPEC,
    KEYWORD_ALIGN,
    OUTPUT_SPEC_TEMPLATE,
    SEGMENTED_BODY_SPEC,
    resolve_title_rule,
)
from common.title_variations import (
    SOHU_DEFAULT_REPEAT_TEMPLATES,
    SOHU_DEFAULT_REPEAT_VARIANTS,
    SOHU_EXP_REPAIR_MARKERS,
    SOHU_TITLE_FALLBACKS,
    render_templates,
)


class GenerationTaskError(RuntimeError):
    def __init__(self, message: str, partial_record: dict):
        super().__init__(message)
        self.partial_record = dict(partial_record)

MODES = {
    "info": ("prompts/article_base.txt", 0.30),
    "light_exp": ("prompts/article_base.txt", 0.24),
    "other_exp": ("prompts/article_base.txt", 0.14),
    "exp": ("prompts/article_exp.txt", 0.32),
}
MODE_NAMES = list(MODES.keys())
MODE_WEIGHTS = [item[1] for item in MODES.values()]
SEGMENTED_MODES = {"info", "light_exp", "other_exp", "exp"}
SECTION_PATTERNS = {
    "opening": r"【开头】\s*(.*?)(?=【中间】|【结尾】|$)",
    "middle": r"【中间】\s*(.*?)(?=【结尾】|$)",
    "ending": r"【结尾】\s*(.*?)$",
}


def _generator_settings() -> dict:
    return get_active_profile().get("generator_settings", {})


def _load(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _foreign_brand_aliases() -> tuple[str, ...]:
    if not _generator_settings().get("normalize_foreign_brands"):
        return ()
    return tuple(get_other_brand_aliases())


def _normalize_brand_text(text: str) -> str:
    text = text or ""
    for alias in _foreign_brand_aliases():
        if alias and alias in text:
            text = text.replace(alias, BRAND)
    return text


def _filter_examples(examples: list[str]) -> list[str]:
    aliases = _foreign_brand_aliases()
    if not aliases or not _generator_settings().get("filter_foreign_examples"):
        return examples
    return [
        example for example in examples
        if not any(alias and alias in example for alias in aliases)
    ]


def _load_examples(platform: str, mode: str = "") -> str:
    candidates = []
    if mode:
        candidates.append(os.path.join("prompts", "examples", f"{platform}_{mode}.txt"))
    candidates.append(os.path.join("prompts", "examples", f"{platform}.txt"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        raw = _load(path)
        if "\n---\n" in raw:
            examples = [entry.strip() for entry in raw.split("\n---\n") if entry.strip()]
        else:
            examples = []
            for block in raw.split("===范文")[1:]:
                content = block.split("===")[0]
                lines = content.split("\n")
                body = "\n".join(line for line in lines if not line.strip().endswith("===")).strip()
                if body:
                    examples.append(body)

        examples = _filter_examples(examples)
        if not examples:
            continue

        parts = [f"【范文{i + 1}】\n{entry}" for i, entry in enumerate(examples)]
        return (
            "\n\n---\n"
            "【风格参考范文：只学语气、结构、立场，禁止复制任何具体内容。】\n\n"
            + "\n\n".join(parts)
        )

    return ""


def _extract_title(raw: str) -> str:
    match = re.search(r"【标题】\s*(.+?)(?:\n|【)", raw, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_segments(raw: str) -> dict:
    segments = {}
    for key, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, raw, re.DOTALL)
        if not match:
            continue
        value = match.group(1).strip().rstrip("】\n")
        if value:
            segments[key] = value
    return segments


def _parse_segmented_output(raw: str) -> tuple[str, dict, str]:
    title = _extract_title(raw)
    segments = _extract_segments(raw)
    if len(segments) == 3:
        article = "\n\n".join([segments["opening"], segments["middle"], segments["ending"]])
        return title, segments, article

    cleaned_raw = raw.replace("【标题】", "").strip()
    if "【正文】" in raw:
        article = raw.split("【正文】", 1)[1].strip()
    else:
        lines = cleaned_raw.split("\n")
        if not title:
            title = lines[0].lstrip("#").strip() if lines else ""
            article = "\n".join(lines[1:]).strip()
        else:
            article = cleaned_raw
    return title, {}, article


def _join_segments(segments: dict) -> str:
    return "\n\n".join([segments.get("opening", ""), segments.get("middle", ""), segments.get("ending", "")]).strip()


def _layer_core(mode: str, keyword: str) -> str:
    prompt_file = MODES[mode][0]
    base = _load(prompt_file)
    if mode in {"info", "light_exp", "other_exp"}:
        return base.replace("{brand}", BRAND).replace("{关键词}", keyword)

    return (
        base
        + f"\n\n关键词：{keyword}"
        + f"\n如需自然提及医院，使用：{BRAND}（只出现 1-2 次，以‘看到/听说’形式，不评价好坏）"
        + "\n基调：整体中立偏正向；如提及不足，一笔带过"
    )


def _layer_voice(profile: str, style: str, trigger: str) -> str:
    return (
        "【角色设定 · 风格层】\n"
        f"- 人设：{profile}\n"
        f"- 表达风格：{style}\n"
        f"- 触发背景：{trigger}"
    )


def _layer_platform(platform: str, platform_prompt: str) -> str:
    return f"【平台适配层】(平台：{platform})\n{platform_prompt}"


def _layer_dynamics() -> dict:
    return {
        "info_density": random.choice(["低", "中", "高"]),
        "hesitation": random.choice(["弱", "中", "强"]),
        "detail_level": random.choice(["少", "中", "多"]),
        "sentence_pattern": random.choice(["短句为主", "长短句混合", "偏长句"]),
    }


def _layer_output_spec(segmented: bool, platform: str = "", mode: str = "") -> str:
    profile = get_active_profile()
    variant = _generator_settings().get("title_rule_variant", profile.get("key", "yiwu_weichuang"))
    title_rule = resolve_title_rule(variant, platform, mode, profile["brand"])
    body_spec = SEGMENTED_BODY_SPEC if segmented else FULL_BODY_SPEC
    return OUTPUT_SPEC_TEMPLATE.substitute(
        keyword_align=KEYWORD_ALIGN,
        title_rule=title_rule,
        body_spec=body_spec,
    )


def _build_prompt(keyword: str, mode: str, profile: str, style: str, trigger: str, platform: str, platform_prompt: str, dynamics: dict) -> tuple[str, bool]:
    segmented = mode in SEGMENTED_MODES
    current_month = datetime.now().month
    core = _layer_core(mode, keyword)
    voice = _layer_voice(profile, style, trigger)
    platform_layer = _layer_platform(platform, platform_prompt)
    examples = _load_examples(platform, mode=mode)
    output_spec = _layer_output_spec(segmented, platform=platform, mode=mode)
    dynamic_text = (
        "【随机因子层】\n"
        f"- 信息密度：{dynamics['info_density']}\n"
        f"- 纠结强度：{dynamics['hesitation']}\n"
        f"- 细节丰富度：{dynamics['detail_level']}\n"
        f"- 句式偏好：{dynamics['sentence_pattern']}"
    )
    prompt = (
        f"当前时间：{current_month}月（季节性活动、节假日、工作安排必须与此一致，"
        f"不得出现与{current_month}月矛盾的内容）\n\n"
        f"{voice}\n\n"
        f"{dynamic_text}\n\n"
        f"{platform_layer}\n\n"
        f"写作模式：{mode}\n\n"
        f"【核心指令层】\n{core}\n"
        f"{examples}"
        f"{output_spec}"
    )
    return prompt, segmented


def _normalize_title(title: str) -> str:
    title = (title or "").strip()
    title = title.replace("，，", "，").replace(",,", ",")
    title = re.sub(r"[，，]{2,}", "，", title)
    title = re.sub(r"\s+", "", title)
    return title.strip("，。；; ")


def _fix_sohu_title(title: str, article: str, mode: str) -> str:
    return _fix_sohu_title_v2(title, article, mode)


def _fix_sohu_title_v2(title: str, article: str, mode: str) -> str:
    title = _normalize_title(title)
    fallback_titles = render_templates(SOHU_TITLE_FALLBACKS["exp" if mode == "exp" else "default"])
    if BRAND not in title:
        title = fallback_titles[sum(ord(ch) for ch in article[:20]) % len(fallback_titles)]

    if mode == "exp":
        if any(item in title for item in SOHU_EXP_REPAIR_MARKERS):
            title = fallback_titles[sum(ord(ch) for ch in article[:20]) % len(fallback_titles)]
    else:
        repeated = set(render_templates(SOHU_DEFAULT_REPEAT_TEMPLATES))
        if title in repeated:
            variants = render_templates(SOHU_DEFAULT_REPEAT_VARIANTS)
            title = variants[sum(ord(ch) for ch in article[:20]) % len(variants)]
    return _normalize_title(title)


_fix_sohu_title = _fix_sohu_title_v2


def _rule_only_eval(article: str, platform: str = "", mode: str = "") -> dict:
    rule = rule_score(article, platform=platform, mode=mode)
    return {
        "score": rule["score"],
        "problems": rule["problems"],
        "reason": rule["reason"],
        "llm": {"score": None, "problems": [], "reason": "skipped_fast_mode"},
        "rule": rule,
    }


def _strip_output_markers(text: str) -> str:
    text = (text or "").strip()
    marker_patterns = (
        r"^\s*#{1,6}\s*",
        r"^\s*【\s*(标题|正文|开头|中间|结尾)\s*】\s*",
        r"^\s*(标题|正文|开头|中间|结尾)\s*[:：]\s*",
    )
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        for pattern in marker_patterns:
            line = re.sub(pattern, "", line, flags=re.IGNORECASE)
        if line:
            cleaned_lines.append(line)
    return "\n\n".join(cleaned_lines).strip()


def _parse_one_shot_output(raw: str) -> tuple[str, str]:
    raw = _normalize_brand_text(raw or "")
    title = _extract_title(raw)
    _, _, article = _parse_segmented_output(raw)
    article = _strip_output_markers(article)
    if not title:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if lines:
            title = _strip_output_markers(lines[0])[:60]
            article = _strip_output_markers("\n".join(lines[1:])) or article
    title = _normalize_title(_strip_output_markers(title))
    return title, article


def _build_one_shot_prompt(keyword: str, mode: str, profile: str, style: str, trigger: str, platform: str, platform_prompt: str, dynamics: dict) -> str:
    current_month = datetime.now().month
    examples = _load_examples(platform, mode=mode)
    title_rule = resolve_title_rule(
        _generator_settings().get("title_rule_variant", get_active_profile().get("key", "yiwu_weichuang")),
        platform,
        mode,
        BRAND,
    )
    return (
        f"你是内容平台文章作者。请只调用你自己的写作能力，一次性输出最终可发布版本。\n\n"
        f"当前月份：{current_month}月。不要写与当前月份明显矛盾的季节、活动或时间信息。\n"
        f"平台：{platform}\n"
        f"主题关键词：{keyword}\n"
        f"品牌/机构：{BRAND}\n"
        f"写作模式：{mode}\n"
        f"人物口吻：{profile}\n"
        f"表达风格：{style}\n"
        f"触发背景：{trigger}\n"
        f"随机写作偏好：信息密度={dynamics['info_density']}，细节={dynamics['detail_level']}，句式={dynamics['sentence_pattern']}\n\n"
        f"平台要求：\n{platform_prompt}\n\n"
        f"标题要求：\n{title_rule}\n"
        f"正文要求：\n"
        f"1. 直接写完整文章，不要分步骤，不要解释创作过程。\n"
        f"2. 标题和正文必须紧扣关键词，标题写什么，正文重点就写什么。\n"
        f"3. 内容像真人随手记录或整理，口语化、自然、有细节，不要写成模板稿。\n"
        f"4. 避免 AI 套路词：首先、其次、再次、最后、总之、综上、值得一提的是。\n"
        f"5. 不要输出【开头】【中间】【结尾】【正文】等结构标签。\n"
        f"6. 不要使用 Markdown，不要编号列表，不要多余说明。\n"
        f"7. 控制在 800-1200 字左右；如果平台要求更短，以平台要求为准。\n"
        f"8. 医疗相关内容保持克制，避免绝对化承诺、专家姓名、具体治疗方案和高风险手术词。\n"
        f"{examples}\n\n"
        f"输出格式：\n"
        f"第一行输出标题。\n"
        f"空一行后输出正文。\n"
    )


def _generate_one_shot_article(keyword: str, platform: str, platform_prompt: str, provider: str, fallback_provider: str, title_suffix: str, record: dict, mode: str, profile: str, style: str, trigger: str, dynamics: dict):
    prompt = _build_one_shot_prompt(keyword, mode, profile, style, trigger, platform, platform_prompt, dynamics)
    with step("[1/1] one-shot article generation"):
        gen_result = call_llm_result(prompt, provider=provider, retries=1, stage="one_shot_generation")
        raw = gen_result.content
        if gen_result.failed and fallback_provider and fallback_provider != provider:
            show_done("one-shot fallback model", fallback_provider)
            gen_result = call_llm_result(prompt, provider=fallback_provider, retries=0, stage="one_shot_generation_fallback")
            raw = gen_result.content
            record["fallback_used"] = True
            record["generator_provider"] = fallback_provider
        if gen_result.failed:
            record["failed_stage"] = "one_shot_generation"
            record["failure_reason"] = gen_result.error or "one-shot generation failed"
            raise GenerationTaskError(record["failure_reason"], record)
        if gen_result.empty:
            record["failed_stage"] = "one_shot_generation"
            record["failure_reason"] = "one-shot generation returned empty content"
            raise GenerationTaskError(record["failure_reason"], record)

    title, article = _parse_one_shot_output(raw)
    if platform == "sohu":
        title = _fix_sohu_title(title, article, mode)
    if title_suffix and title:
        title = f"{title}{title_suffix}"

    eval_result = _rule_only_eval(article, platform=platform, mode=mode)
    min_score = PLATFORM_MIN_SCORE.get(platform, MIN_SCORE)
    record.update({
        "title": title,
        "first_draft_length": len(article),
        "first_draft_score": eval_result["score"],
        "first_draft_problems": eval_result["problems"],
        "first_draft_reason": eval_result["reason"],
        "first_draft_llm_score": None,
        "first_draft_rule_score": eval_result["rule"]["score"],
        "retries": max(0, gen_result.attempts - 1),
        "final_score": eval_result["score"],
        "final_problems": eval_result["problems"],
        "final_reason": eval_result["reason"],
        "final_llm_score": None,
        "final_rule_score": eval_result["rule"]["score"],
        "final_length": len(article),
        "after_antiai_length": len(article),
        "min_score": min_score,
        "passed": eval_result["score"] >= min_score,
        "quality_mode": "one_shot",
        "quality_steps_skipped": ["keyword_expand", "llm_score", "anti_ai", "llm_rewrite"],
        "has_segments": False,
    })
    show_score(eval_result["score"], min_score)
    return title, article, record


def _safe_anti_ai(article: str, record: dict, stage: str) -> str:
    try:
        article_after = anti_ai_pipeline(article)
    except Exception as exc:
        record.setdefault("warnings", []).append(f"{stage}: anti_ai skipped: {exc}")
        return article
    if article_after and len(article_after) > 50:
        return _normalize_brand_text(article_after)
    record.setdefault("warnings", []).append(f"{stage}: anti_ai returned empty/short content")
    return article


def generate_article(
    keyword: str,
    platform: str,
    platform_prompt: str,
    generator_provider: str = None,
    fallback_provider: str = None,
    title_suffix: str = "",
    generation_mode: str = "fast",
):
    provider = generator_provider or DRAFT_PROVIDER or GENERATOR_PROVIDER
    generation_mode = (generation_mode or "fast").strip().lower()
    if generation_mode not in {"fast", "quality", "one_shot"}:
        generation_mode = "fast"
    mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS)[0]
    profile = random_profile(platform)
    style = random_style(profile)
    trigger = random_trigger(keyword=keyword)
    dynamics = _layer_dynamics()
    prompt, segmented = _build_prompt(keyword, mode, profile, style, trigger, platform, platform_prompt, dynamics)

    show_params(mode, profile)

    record = {
        "mode": mode,
        "profile": profile,
        "style": style,
        "trigger": trigger,
        "dynamics": dynamics,
        "segmented": segmented,
        "retries": 0,
        "retry_scores": [],
        "rewrite_targets": [],
        "generator_provider": provider,
        "fallback_used": False,
        "failed_stage": "",
        "failure_reason": "",
        "generation_mode": generation_mode,
        "warnings": [],
    }

    if generation_mode == "one_shot":
        return _generate_one_shot_article(
            keyword,
            platform,
            platform_prompt,
            provider,
            fallback_provider,
            title_suffix,
            record,
            mode,
            profile,
            style,
            trigger,
            dynamics,
        )

    with step("[1/3] 生成初稿 + 标题"):
        gen_result = call_llm_result(prompt, provider=provider, retries=1, stage="draft_generation")
        raw = gen_result.content
        if gen_result.failed and fallback_provider and fallback_provider != provider:
            show_done("首稿失败，回退模型", fallback_provider)
            gen_result = call_llm_result(prompt, provider=fallback_provider, retries=1, stage="draft_generation_fallback")
            raw = gen_result.content
            record["fallback_used"] = True
            record["generator_provider"] = fallback_provider
        if gen_result.failed:
            record["failed_stage"] = "draft_generation"
            record["failure_reason"] = gen_result.error or "首稿生成失败"
            raise GenerationTaskError(record["failure_reason"], record)
        if gen_result.empty:
            record["failed_stage"] = "draft_generation"
            record["failure_reason"] = "首稿生成返回空内容"
            raise GenerationTaskError(record["failure_reason"], record)

    title, segments, article = _parse_segmented_output(raw)
    title = _normalize_brand_text(title)
    article = _normalize_brand_text(article)
    segments = {name: _normalize_brand_text(value) for name, value in segments.items()}

    if platform == "sohu":
        title = _fix_sohu_title(title, article, mode)
    if title_suffix and title:
        title = f"{title}{title_suffix}"
    record["title"] = title

    record["first_draft_length"] = len(article)
    record["has_segments"] = bool(segments)
    short_title = (title[:28] + "...") if len(title) > 28 else title
    show_done("[1/3] 初稿完成", short_title)

    first_eval = _rule_only_eval(article, platform=platform, mode=mode) if generation_mode == "fast" else score_article_detailed(article, platform=platform, mode=mode)
    if first_eval["score"] < 0 and generation_mode == "quality":
        record.setdefault("warnings", []).append(f"quality score skipped: {first_eval['reason']}")
        first_eval = _rule_only_eval(article, platform=platform, mode=mode)
    if first_eval["score"] < 0:
        record["failed_stage"] = "first_score"
        record["failure_reason"] = first_eval["reason"]
        raise GenerationTaskError(first_eval["reason"], record)
    record["first_draft_score"] = first_eval["score"]
    record["first_draft_problems"] = first_eval["problems"]
    record["first_draft_reason"] = first_eval["reason"]
    record["first_draft_llm_score"] = first_eval["llm"]["score"]
    record["first_draft_rule_score"] = first_eval["rule"]["score"]

    if generation_mode == "fast":
        min_score = PLATFORM_MIN_SCORE.get(platform, MIN_SCORE)
        score, problems = first_eval["score"], first_eval["problems"]
        record.update({
            "retries": 0,
            "final_score": score,
            "final_problems": problems,
            "final_reason": first_eval["reason"],
            "final_llm_score": None,
            "final_rule_score": first_eval["rule"]["score"],
            "final_length": len(article),
            "after_antiai_length": len(article),
            "min_score": min_score,
            "passed": score >= min_score,
            "title": title,
            "quality_steps_skipped": ["llm_score", "anti_ai", "llm_rewrite"],
        })
        show_score(score, min_score)
        return title, article, record

    min_score = PLATFORM_MIN_SCORE.get(platform, MIN_SCORE)
    score, problems = first_eval["score"], first_eval["problems"]
    show_score(score, min_score)

    retry = 0
    eval_result = first_eval
    if score < min_score:
        retry = 1
        targets = pick_target_segments(problems) if segments else []
        record["rewrite_targets"].append(targets if segments else ["whole"])
        show_retry(retry, score, 1)
        with step(f"  robust rewrite [{','.join(targets) if segments else 'whole'}]"):
            try:
                if segments and targets:
                    for segment_name in targets:
                        old_segment = segments.get(segment_name, "")
                        if not old_segment:
                            continue
                        new_segment = rewrite_segment(segment_name, old_segment, problems)
                        if new_segment and len(new_segment) > 20:
                            segments[segment_name] = _normalize_brand_text(new_segment)
                    article = _join_segments(segments)
                else:
                    article = _normalize_brand_text(apply_random_rewrite(article) or article)
                record["robust_rewrite_applied"] = True
            except Exception as exc:
                record.setdefault("warnings", []).append(f"robust rewrite skipped: {exc}")
                record["robust_rewrite_applied"] = False

        eval_result = _rule_only_eval(article, platform=platform, mode=mode)
        score, problems = eval_result["score"], eval_result["problems"]
        record["retry_scores"].append(score)
        show_score(score, min_score)

    record.update({
        "retries": retry,
        "final_score": score,
        "final_problems": problems,
        "final_reason": eval_result["reason"],
        "final_llm_score": eval_result["llm"]["score"],
        "final_rule_score": eval_result["rule"]["score"],
        "final_length": len(article),
        "after_antiai_length": len(article),
        "min_score": min_score,
        "passed": score >= min_score,
        "title": title,
        "quality_mode": "robust",
        "quality_steps_skipped": ["anti_ai", "llm_rescore_loop"],
    })
    return title, article, record

    with step("[2/3] 去AI化"):
        article = _safe_anti_ai(article, record, "initial")
        if segments:
            segments = _resplit_segments(article)
    record["after_antiai_length"] = len(article)
    show_done("[2/3] 去AI化完成")

    with step("[3/3] 质量评分"):
        eval_result = score_article_detailed(article, platform=platform, mode=mode)
    if eval_result["score"] < 0:
        record["failed_stage"] = "final_score"
        record["failure_reason"] = eval_result["reason"]
        raise GenerationTaskError(eval_result["reason"], record)
    score, problems = eval_result["score"], eval_result["problems"]
    min_score = PLATFORM_MIN_SCORE.get(platform, MIN_SCORE)
    show_score(score, min_score)

    retry = 0
    while score < min_score and retry < MAX_RETRY:
        retry += 1
        show_retry(retry, score, MAX_RETRY)
        targets = pick_target_segments(problems) if segments else []
        record["rewrite_targets"].append(targets if segments else ["whole"])

        with step(f"  局部改写[{','.join(targets) if segments else '整篇'}]"):
            try:
                if segments and targets:
                    for segment_name in targets:
                        old_segment = segments.get(segment_name, "")
                        if not old_segment:
                            continue
                        new_segment = rewrite_segment(segment_name, old_segment, problems)
                        if new_segment and len(new_segment) > 20:
                            segments[segment_name] = _normalize_brand_text(new_segment)
                    article = _join_segments(segments)
                else:
                    article = apply_random_rewrite(article) or article
            except Exception as exc:
                record.setdefault("warnings", []).append(f"rewrite skipped: {exc}")
            article = _safe_anti_ai(article, record, f"retry_{retry}")
            if segments:
                segments = _resplit_segments(article)

        with step("  重新评分"):
            eval_result = score_article_detailed(article, platform=platform, mode=mode)
        if eval_result["score"] < 0:
            record["failed_stage"] = "retry_score"
            record["failure_reason"] = eval_result["reason"]
            raise GenerationTaskError(eval_result["reason"], record)
        score, problems = eval_result["score"], eval_result["problems"]
        show_score(score, min_score)
        record["retry_scores"].append(score)

    record.update({
        "retries": retry,
        "final_score": score,
        "final_problems": problems,
        "final_reason": eval_result["reason"],
        "final_llm_score": eval_result["llm"]["score"],
        "final_rule_score": eval_result["rule"]["score"],
        "final_length": len(article),
        "min_score": min_score,
        "passed": score >= min_score,
        "title": title,
    })
    return title, article, record


def _resplit_segments(article: str) -> dict:
    paragraphs = [paragraph for paragraph in article.split("\n\n") if paragraph.strip()]
    if len(paragraphs) < 3:
        return {"opening": "", "middle": article, "ending": ""}

    count = len(paragraphs)
    opening_size = max(1, count // 4)
    ending_size = max(1, count // 4)
    middle_size = count - opening_size - ending_size
    opening = "\n\n".join(paragraphs[:opening_size])
    middle = "\n\n".join(paragraphs[opening_size:opening_size + middle_size])
    ending = "\n\n".join(paragraphs[opening_size + middle_size:])
    return {"opening": opening, "middle": middle, "ending": ending}
