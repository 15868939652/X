from datetime import datetime

from common import legacy_prompt_builder as legacy
from common.prompt_parser import (
    SECTION_PATTERNS,
    extract_segments,
    extract_title,
    join_segments,
    parse_segmented_output,
    resplit_segments,
)
from common.prompt_rules import (
    FULL_BODY_SPEC,
    KEYWORD_ALIGN,
    OUTPUT_SPEC_TEMPLATE,
    SEGMENTED_BODY_SPEC,
    resolve_title_rule,
)
from common.prompt_templates import (
    render_core_layer,
    render_dynamic_layer,
    render_platform_layer,
    render_prompt_frame,
    render_voice_layer,
)

MODES = legacy.MODES
MODE_NAMES = legacy.MODE_NAMES
MODE_WEIGHTS = legacy.MODE_WEIGHTS
SEGMENTED_MODES = legacy.SEGMENTED_MODES

_generator_settings = legacy._generator_settings
_load = legacy._load
_foreign_brand_aliases = legacy._foreign_brand_aliases
_normalize_brand_text = legacy._normalize_brand_text
_filter_examples = legacy._filter_examples
_load_examples = legacy._load_examples
_normalize_title = legacy._normalize_title
_fix_sohu_title = legacy._fix_sohu_title
_layer_dynamics = legacy._layer_dynamics

_extract_title = extract_title
_extract_segments = extract_segments
_parse_segmented_output = parse_segmented_output
_join_segments = join_segments
_resplit_segments = resplit_segments


def _layer_core(mode: str, keyword: str) -> str:
    return render_core_layer(mode, keyword)


def _layer_voice(profile: str, style: str, trigger: str) -> str:
    return render_voice_layer(profile, style, trigger)


def _layer_platform(platform: str, platform_prompt: str) -> str:
    return render_platform_layer(platform, platform_prompt)


def _layer_output_spec(segmented: bool, platform: str = "", mode: str = "") -> str:
    profile = legacy.get_active_profile()
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
    dynamic_text = render_dynamic_layer(dynamics)
    prompt = render_prompt_frame(
        current_month=current_month,
        voice=voice,
        dynamic_text=dynamic_text,
        platform_layer=platform_layer,
        mode=mode,
        core=core,
        examples=examples,
        output_spec=output_spec,
    )
    return prompt, segmented


def build_prompt_snapshot(keyword: str, mode: str, profile: str, style: str, trigger: str, platform: str, platform_prompt: str, dynamics: dict) -> dict:
    prompt, segmented = _build_prompt(keyword, mode, profile, style, trigger, platform, platform_prompt, dynamics)
    return {"prompt": prompt, "segmented": segmented}


legacy.SECTION_PATTERNS = SECTION_PATTERNS
legacy._extract_title = _extract_title
legacy._extract_segments = _extract_segments
legacy._parse_segmented_output = _parse_segmented_output
legacy._join_segments = _join_segments
legacy._resplit_segments = _resplit_segments
legacy._layer_core = _layer_core
legacy._layer_voice = _layer_voice
legacy._layer_platform = _layer_platform
legacy._layer_output_spec = _layer_output_spec
legacy._build_prompt = _build_prompt


generate_article = legacy.generate_article
