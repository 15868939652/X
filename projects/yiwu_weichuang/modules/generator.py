"""
文章生成流程 (v3)：
  1. 随机参数 → 组装四层 Prompt
  2. 一次 pro 调用输出【开头】【中间】【结尾】三段 + 标题
  3. 初稿评分（LLM 0.7 + 规则 0.3）
  4. 去 AI 化（lite，整篇）
  5. 复评分
  6. 若不达标：按问题标签定位要改的段，只重写那一段，其余保留
  7. 重复第 5-6 步最多 MAX_RETRY 次
"""

import os
import random
import re
from datetime import datetime
from functools import lru_cache

from config import BRAND, MIN_SCORE, MAX_RETRY, PLATFORM_MIN_SCORE, GENERATOR_PROVIDER
from modules.profile_loader import get_active_profile, get_other_brand_aliases
from modules.llm import call_llm
from modules.randomizer import random_profile, random_style, random_trigger
from modules.anti_ai import anti_ai_pipeline
from modules.rewriter import rewrite_segment, pick_target_segments, apply_random_rewrite
from modules.scorer import score_article_detailed
from modules.progress import show_params, show_done, show_score, show_retry, step


# ========================= 文章模式配置 =========================
_MODES = {
    "info":       ("prompts/article_base.txt",      0.30),
    "light_exp":  ("prompts/article_base.txt",      0.24),
    "other_exp":  ("prompts/article_base.txt",      0.14),
    "exp":        ("prompts/article_exp.txt",       0.32),
}
_MODE_NAMES   = list(_MODES.keys())
_MODE_WEIGHTS = [v[1] for v in _MODES.values()]

# 支持分段输出的模式（其他模式太短，不做分段）
_SEGMENTED_MODES = {"info", "light_exp", "other_exp", "exp"}
_FOREIGN_BRAND_ALIASES = tuple(get_other_brand_aliases())


def _load(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _normalize_brand_text(text: str) -> str:
    text = text or ""
    for alias in _FOREIGN_BRAND_ALIASES:
        if alias and alias in text:
            text = text.replace(alias, BRAND)
    return text


def _filter_examples(examples: list[str]) -> list[str]:
    filtered = []
    for example in examples:
        if any(alias and alias in example for alias in _FOREIGN_BRAND_ALIASES):
            continue
        filtered.append(example)
    return filtered


def _load_examples(platform: str, mode: str = "") -> str:
    """
    优先读 {platform}_{mode}.txt（review_ui 写入的人工标注范文）；
    fallback 到旧的 {platform}.txt（旧格式兼容）。
    新格式用 \\n---\\n 分隔；旧格式用 ===范文 分隔。
    结果不缓存：review_ui 随时可能写入新范文，需要实时生效。
    """
    candidates = []
    if mode:
        candidates.append(os.path.join("prompts", "examples", f"{platform}_{mode}.txt"))
    candidates.append(os.path.join("prompts", "examples", f"{platform}.txt"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        raw = _load(path)

        # 新格式：\n---\n 分隔
        if "\n---\n" in raw:
            examples = [e.strip() for e in raw.split("\n---\n") if e.strip()]
        else:
            # 旧格式：===范文N=== 分隔
            examples = []
            for block in raw.split("===范文")[1:]:
                content = block.split("===")[0]
                lines   = content.split("\n")
                body    = "\n".join(l for l in lines
                                    if not l.strip().endswith("===")).strip()
                if body:
                    examples.append(body)

        examples = _filter_examples(examples)
        if not examples:
            continue

        parts = [f"【范文{i+1}】\n{ex}" for i, ex in enumerate(examples)]
        return (
            "\n\n---\n"
            "【风格参考范文：只学语气、结构、立场，禁止复制任何具体内容】\n\n"
            + "\n\n".join(parts)
        )

    return ""


# ========================= 输出解析 =========================

def _parse_segmented_output(raw: str) -> tuple:
    """
    解析形如:
        【标题】...
        【开头】...
        【中间】...
        【结尾】...
    的输出。若缺失任意段落则降级为整体文章。
    返回 (title, segments_dict, article_text)
    segments_dict 可能为空 dict（降级情况），此时 article_text 为完整文本。
    """
    title = ""
    m = re.search(r"【标题】\s*(.+?)(?:\n|【)", raw, re.DOTALL)
    if m:
        title = m.group(1).strip()

    segs = {}
    for key, pat in [
        ("opening", r"【开头】\s*(.*?)(?=【中间】|【结尾】|$)"),
        ("middle",  r"【中间】\s*(.*?)(?=【结尾】|$)"),
        ("ending",  r"【结尾】\s*(.*?)$"),
    ]:
        mm = re.search(pat, raw, re.DOTALL)
        if mm:
            val = mm.group(1).strip()
            # 去掉结尾可能残留的 】或其它分隔
            val = val.rstrip("】 \n")
            if val:
                segs[key] = val

    if len(segs) == 3:
        article = "\n\n".join([segs["opening"], segs["middle"], segs["ending"]])
        return title, segs, article

    # 降级：没按格式输出，就按老方式解析正文
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


def _join_segments(segs: dict) -> str:
    return "\n\n".join([segs.get("opening", ""), segs.get("middle", ""), segs.get("ending", "")]).strip()


# ========================= 四层 Prompt 组装 =========================

def _layer_core(mode: str, keyword: str, segmented: bool) -> str:
    """核心层：角色 + 关键词 + 写作模式 + 结构硬约束"""
    prompt_file = _MODES[mode][0]
    base = _load(prompt_file)
    if mode in ("info", "light_exp", "other_exp"):
        base = base.replace("{brand}", BRAND).replace("{关键词}", keyword)
    else:
        base += (
            f"\n\n关键词：{keyword}"
            f"\n如需自然提及医院，使用：{BRAND}（只出现 1-2 次，以'看到/听说'形式，不评价好坏）"
            f"\n基调：整体中立偏正向；如提及不足，一笔带过"
        )
    return base


def _layer_voice(profile: str, style: str, trigger: str) -> str:
    """风格层：人设 + 表达风格 + 触发背景"""
    return (
        "【角色设定 · 风格层】\n"
        f"- 人设：{profile}\n"
        f"- 表达风格：{style}\n"
        f"- 触发背景：{trigger}"
    )


def _layer_platform(platform: str, platform_prompt: str) -> str:
    """平台层"""
    return f"【平台适配层】(平台：{platform})\n{platform_prompt}"


def _layer_dynamics() -> dict:
    """随机层：信息密度/纠结强度/细节丰富度/句式偏好"""
    return {
        "info_density":     random.choice(["低", "中", "高"]),
        "hesitation":       random.choice(["弱", "中", "强"]),
        "detail_level":     random.choice(["少", "中", "多"]),
        "sentence_pattern": random.choice(["短句为主", "长短句混合", "偏长句"]),
    }


def _layer_output_spec(segmented: bool, platform: str = "", mode: str = "") -> str:
    """输出规格层（分段 vs 整体）"""
    profile = get_active_profile()
    brand = profile["brand"]

    if platform == "sohu":
        if mode == "exp":
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-26 字：\n"
                f"  标题不要求以『{brand}』开头，但正文第一句必须自然出现一次『{brand}』。\n"
                "  第一段只能写已经发生过的经历型陈述，如【那次去看后的感受 / 一次就诊后的记录 / 那天就诊过程里的印象 / 看完之后记下来的情况】。\n"
                "  只能描述经历和感受，不加判断，不给建议，不写问句。\n"
                "  禁止出现具体科室、具体病种、具体症状、检查项目、治疗项目、专家姓名。\n"
                "  【禁用词】值不值得、适不适合、靠谱吗、怎么样、好不好、怎么了、行不行、建议、推荐、不孕不育、宫外孕、输卵管、私密整形、纪亚忠\n"
                "  第二段：从以下表达里随机换着写，不要总用同一句：\n"
                "    说说我那次看完后的感觉 / 记录一下那次就诊留下的印象 / 聊聊我看完之后最在意的几个点 / 把那次经历顺手记一下\n"
                "  不要营销感，不要感叹号，不要写成总结口吻。\n"
            )
        else:
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-26 字：\n"
                f"  标题不要求以『{brand}』开头，但正文第一句必须自然出现一次『{brand}』。\n"
                "  第一段只能写纯描述型表达，如【实地了解了一下 / 最近留意到一些情况 / 我这次顺手查了查 / 相关信息整理了一下 / 看到一些本地讨论】，\n"
                "  只能描述信息，不加判断，不给建议，不写问句。\n"
                "  禁止出现具体科室、具体病种、具体症状、检查项目、治疗项目、专家姓名。\n"
                "  【禁用词】值不值得、适不适合、靠谱吗、怎么样、好不好、怎么了、行不行、建议、推荐、不孕不育、宫外孕、输卵管、私密整形、纪亚忠\n"
                "  第二段：从以下表达里随机换着写，不要总用同一句：\n"
                "    说说我了解到的情况 / 记录一下我打听到的信息 / 聊聊我这次整理下来的印象 / 把我查到的内容顺手记一下 / 讲讲我这次了解后的感觉 / 随手记一下我这次看的几个点\n"
                "  不要营销感，不要感叹号；『实地了解了一下』可以用，但必须与其他表达轮换，不能高频重复。\n"
            )
    elif platform == "baijiahao":
        if mode == "exp":
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-28 字：\n"
                f"  第一段：以『{brand}』开头，写已经发生过的就诊经历，但用泛化表达，例：去看过一次 / 那次就诊后的感受 / 看完之后的真实印象\n"
                "  禁止出现高风险手术词、具体病种和专家姓名。\n"
                "  第二段：第一人称经历型尾巴，例：说说我那次看完后的感觉 / 讲讲那次就诊过程里让我记住的点 / 记录一下我看完后的真实印象\n"
                "  不要营销感，不要感叹号，不要写成查资料口气。\n"
            )
        else:
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-28 字：\n"
                f"  第一段：以『{brand}』开头，延伸用【了解类/体验类】词语，\n"
                "    例：去看了一次后的印象 / 最近了解下来的情况 / 相关信息整理了一下 / 就诊前后的一点感受\n"
                "  禁止出现值不值得、适不适合、具体病种、手术词、专家姓名。\n"
                "  第二段：第一人称了解型尾巴，例：说说我了解到的情况 / 聊聊我打听后的印象 / 记录一下我这次整理下来的内容\n"
                "  不要营销感，不要感叹号，也不要高频重复『实地了解了一下』\n"
            )
    else:
        if mode == "exp":
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-28 字：\n"
                f"  第一段：以『{brand}』开头，强调已经发生过的就诊经历，例：去看过一次后的感受 / 那次看完之后的印象 / 就诊过程里的真实体验\n"
                "  如果涉及不孕不育、会诊、专业项目，也尽量转写成普通人能接受的泛化表达，不直接堆术语。\n"
                "  第二段：第一人称经历型短语，例：说说我那次看完后的感觉 / 讲讲那次过程里我最在意的点 / 聊聊我看完之后的真实想法\n"
                "  不要营销感，不要感叹号，也不要写成查资料或整理信息的口气。\n"
            )
        else:
            title_rule = (
                "【标题】两段式，逗号分隔，共 15-28 字：\n"
                f"  第一段：以『{brand}』开头 + 关键词延伸（疑问/经历/体验风格），但高专业方向要尽量写成普通人能接受的表达\n"
                f"    例：{brand}靠谱吗 / {brand}怎么样 / 去过的人怎么说\n"
                "  第二段：第一人称个人视角短语，且要主动换表达，例：说说我打听后的情况 / 聊聊我最近的了解 / 说说我的真实感受 / 讲讲我整理下来的信息\n"
                "  不要营销感，不要感叹号，也不要高频重复同一句标题尾巴\n"
            )

    keyword_align = (
        "【内容对齐硬约束】标题写了什么，正文就重点写什么：\n"
        "  - 标题含【技术/效果/水平】→ 正文必须有医生诊疗能力、检查是否仔细、对症情况的描述\n"
        "  - 标题含【费用/收费/价格】→ 正文必须有费用区间或费用相关信息\n"
        "  - 标题含【流程/怎么预约/怎么挂号】→ 正文必须有就诊流程的描述\n"
        "  - 标题含【靠谱/值不值得/好不好】→ 正文必须有综合评价信息，不能只写方便不方便\n"
        "  - 如果 mode=exp，标题和正文都必须体现“已经去看过”的经历感，不能写成查资料口气。\n"
        "  - 搜狐这类陈述型标题，正文必须对应标题里提到的了解内容，不能标题写A正文全写B。\n"
        "  禁止出现标题和正文重点不一致的情况。\n\n"
    )

    if segmented:
        return (
            "\n\n---\n【输出格式（必须严格遵守）】\n"
            + keyword_align
            + title_rule +
            "【开头】(约占全文 20-30%)\n"
            "  写开头段，要有具体的生活场景切入\n"
            "【中间】(约占全文 50-60%，信息密度最高的部分)\n"
            "  写中间段，必须满足 article_base 里对中间段的硬约束\n"
            "【结尾】(约占全文 15-25%)\n"
            "  写开放式结尾，禁止总结\n"
            "\n严格按上述四个标签输出，不要输出其他内容。"
        )
    return (
        "\n\n---\n【输出格式（必须严格遵守）】\n"
        + keyword_align
        + title_rule +
        "【正文】\n（在此写正文内容）"
    )


def _build_prompt(keyword: str, mode: str, profile: str, style: str,
                  trigger: str, platform: str, platform_prompt: str,
                  dynamics: dict) -> tuple:
    """返回 (prompt, segmented_flag)"""
    segmented = mode in _SEGMENTED_MODES
    current_month = datetime.now().month

    core    = _layer_core(mode, keyword, segmented)
    voice   = _layer_voice(profile, style, trigger)
    plat    = _layer_platform(platform, platform_prompt)
    examples = _load_examples(platform, mode=mode)
    spec    = _layer_output_spec(segmented, platform=platform)

    dyn_text = (
        "【随机因子层】\n"
        f"- 信息密度：{dynamics['info_density']}\n"
        f"- 纠结强度：{dynamics['hesitation']}\n"
        f"- 细节丰富度：{dynamics['detail_level']}\n"
        f"- 句式偏好：{dynamics['sentence_pattern']}"
    )

    prompt = (
        f"当前时间：{current_month}月（季节性活动/节假日/工作安排必须与此一致，"
        f"不得出现与{current_month}月矛盾的内容）\n\n"
        f"{voice}\n\n"
        f"{dyn_text}\n\n"
        f"{plat}\n\n"
        f"写作模式：{mode}\n\n"
        f"【核心指令层】\n{core}\n"
        f"{examples}"
        f"{spec}"
    )
    return prompt, segmented


def _normalize_title(title: str) -> str:
    title = (title or "").strip()
    title = title.replace("，，", "，").replace(",,", ",")
    title = re.sub(r"[，,]{2,}", "，", title)
    title = re.sub(r"\s+", "", title)
    title = title.strip("，,。；; ")
    return title


def _fix_sohu_title(title: str, article: str, mode: str) -> str:
    title = _normalize_title(title)
    if BRAND not in title:
        if mode == "exp":
            title = f"{BRAND}就诊过程记录，说说我那次看完后的感觉"
        else:
            title = f"{BRAND}实地了解了一下，说说我了解到的情况"

    if mode == "exp":
        if any(x in title for x in ["查到", "了解到的情况", "整理下来的印象"]):
            title = f"{BRAND}就诊过程记录，说说我那次看完后的感觉"
    else:
        if title in (
            f"{BRAND}实地了解了一下，说说我了解到的情况",
            f"{BRAND}实地了解了一下，说说我查到的情况",
        ):
            variants = [
                f"{BRAND}实地了解了一下，说说我打听到的信息",
                f"{BRAND}最近留意到一些情况，聊聊我整理下来的印象",
                f"{BRAND}相关信息整理了一下，说说我了解到的情况",
            ]
            pick = sum(ord(c) for c in article[:20]) % len(variants)
            title = variants[pick]

    return _normalize_title(title)


# ========================= 主流程 =========================

def generate_article(keyword: str, platform: str, platform_prompt: str,
                     generator_provider: str = None, fallback_provider: str = None,
                     title_suffix: str = ""):
    """
    返回 (title, article, record)
    record 包含分段生成 / 评分 / 重写的完整过程数据
    """
    provider = generator_provider or GENERATOR_PROVIDER
    mode    = random.choices(_MODE_NAMES, weights=_MODE_WEIGHTS)[0]
    profile = random_profile(platform)
    style   = random_style(profile)
    trigger = random_trigger(keyword=keyword)
    dynamics = _layer_dynamics()
    prompt, segmented = _build_prompt(keyword, mode, profile, style, trigger,
                                      platform, platform_prompt, dynamics)

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
    }

    # ----- Step 1: 生成初稿（含三段落结构）-----
    with step("[1/3] 生成初稿 + 标题"):
        raw = call_llm(prompt, provider=provider)
        if (not raw or not raw.strip()) and fallback_provider and fallback_provider != provider:
            show_done("首稿失败，回退模型", fallback_provider)
            raw = call_llm(prompt, provider=fallback_provider)
            record["fallback_used"] = True
            record["generator_provider"] = fallback_provider
    title, segments, article = _parse_segmented_output(raw)
    title = _normalize_brand_text(title)
    article = _normalize_brand_text(article)
    segments = {name: _normalize_brand_text(value) for name, value in segments.items()}
    if platform == "sohu":
        title = _fix_sohu_title(title, article, mode)
    if title_suffix and title:
        title = f"{title}{title_suffix}"
    record["first_draft_length"] = len(article)
    record["has_segments"] = bool(segments)
    short_title = (title[:28] + "…") if len(title) > 28 else title
    show_done("[1/3] 初稿完成", short_title)

    # ----- Step 2: 初稿评分（不做去AI化之前的基准）-----
    first_eval = score_article_detailed(article, platform=platform, mode=mode)
    record["first_draft_score"] = first_eval["score"]
    record["first_draft_problems"] = first_eval["problems"]
    record["first_draft_reason"] = first_eval["reason"]
    record["first_draft_llm_score"] = first_eval["llm"]["score"]
    record["first_draft_rule_score"] = first_eval["rule"]["score"]

    # ----- Step 3: 去 AI 化（轻量模型，整篇）-----
    with step("[2/3] 去AI化"):
        article_after = anti_ai_pipeline(article)
    if article_after and len(article_after) > 50:
        article = _normalize_brand_text(article_after)
        # 去AI化后分段信息失效：若后续需要局部改写，重新拆一下
        if segments:
            segments = _resplit_segments(article, segments)
    record["after_antiai_length"] = len(article)
    show_done("[2/3] 去AI化完成")

    # ----- Step 4: 评分 -----
    with step("[3/3] 质量评分"):
        eval_ = score_article_detailed(article, platform=platform, mode=mode)
    score, problems = eval_["score"], eval_["problems"]
    min_score = PLATFORM_MIN_SCORE.get(platform, MIN_SCORE)
    show_score(score, min_score)

    # ----- Step 5: 重试（问题驱动局部重写）-----
    retry = 0
    while score < min_score and retry < MAX_RETRY:
        retry += 1
        show_retry(retry, score, MAX_RETRY)

        targets = pick_target_segments(problems) if segments else []
        record["rewrite_targets"].append(targets if segments else ["whole"])

        with step(f"  局部改写 [{','.join(targets) if segments else '整篇'}]"):
            if segments and targets:
                for seg_name in targets:
                    old_seg = segments.get(seg_name, "")
                    if not old_seg:
                        continue
                    new_seg = rewrite_segment(seg_name, old_seg, problems)
                    if new_seg and len(new_seg) > 20:
                        segments[seg_name] = _normalize_brand_text(new_seg)
                article = _join_segments(segments)
            else:
                # 降级：整篇重写
                article = apply_random_rewrite(article)
            article = _normalize_brand_text(anti_ai_pipeline(article) or article)
            if segments:
                segments = _resplit_segments(article, segments)

        with step("  重新评分"):
            eval_ = score_article_detailed(article, platform=platform, mode=mode)
        score, problems = eval_["score"], eval_["problems"]
        show_score(score, min_score)
        record["retry_scores"].append(score)

    record.update({
        "retries": retry,
        "final_score": score,
        "final_problems": problems,
        "final_reason": eval_["reason"],
        "final_llm_score": eval_["llm"]["score"],
        "final_rule_score": eval_["rule"]["score"],
        "final_length": len(article),
        "min_score": min_score,
        "passed": score >= min_score,
        "title": title,
    })

    return title, article, record


def _resplit_segments(article: str, prior_segments: dict) -> dict:
    """
    去AI化/整体改写后，原分段边界被破坏。
    简单地按段落数三等分，保留 segments 结构供下一轮局部改写用。
    """
    paras = [p for p in article.split("\n\n") if p.strip()]
    if len(paras) < 3:
        # 无法重分段，把全文塞到 middle，保留空 opening/ending
        return {"opening": "", "middle": article, "ending": ""}
    n = len(paras)
    a = max(1, n // 4)
    c = max(1, n // 4)
    b = n - a - c
    opening = "\n\n".join(paras[:a])
    middle  = "\n\n".join(paras[a:a + b])
    ending  = "\n\n".join(paras[a + b:])
    return {"opening": opening, "middle": middle, "ending": ending}
