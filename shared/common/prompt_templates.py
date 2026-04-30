from string import Template

from common import legacy_prompt_builder as legacy


_SENTINELS = {
    "keyword": "__CODEX_KEYWORD__",
    "profile": "__CODEX_PROFILE__",
    "style": "__CODEX_STYLE__",
    "trigger": "__CODEX_TRIGGER__",
    "platform": "__CODEX_PLATFORM__",
    "platform_prompt": "__CODEX_PLATFORM_PROMPT__",
    "info_density": "__CODEX_INFO_DENSITY__",
    "hesitation": "__CODEX_HESITATION__",
    "detail_level": "__CODEX_DETAIL_LEVEL__",
    "sentence_pattern": "__CODEX_SENTENCE_PATTERN__",
    "current_month": "__CODEX_CURRENT_MONTH__",
    "dynamic_text": "__CODEX_DYNAMIC_TEXT__",
    "voice": "__CODEX_VOICE__",
    "platform_layer": "__CODEX_PLATFORM_LAYER__",
    "mode": "__CODEX_MODE__",
    "core": "__CODEX_CORE__",
    "examples": "__CODEX_EXAMPLES__",
    "output_spec": "__CODEX_OUTPUT_SPEC__",
}


def _to_template(text: str, replacements: dict[str, str]) -> Template:
    for key, sentinel in replacements.items():
        text = text.replace(sentinel, f"${{{key}}}")
    return Template(text)


CORE_LAYER_TEMPLATES = {
    mode: _to_template(legacy._layer_core(mode, _SENTINELS["keyword"]), {"keyword": _SENTINELS["keyword"]})
    for mode in legacy.MODES
}

VOICE_LAYER_TEMPLATE = _to_template(
    legacy._layer_voice(_SENTINELS["profile"], _SENTINELS["style"], _SENTINELS["trigger"]),
    {
        "profile": _SENTINELS["profile"],
        "style": _SENTINELS["style"],
        "trigger": _SENTINELS["trigger"],
    },
)

PLATFORM_LAYER_TEMPLATE = _to_template(
    legacy._layer_platform(_SENTINELS["platform"], _SENTINELS["platform_prompt"]),
    {
        "platform": _SENTINELS["platform"],
        "platform_prompt": _SENTINELS["platform_prompt"],
    },
)


_def_platform = _SENTINELS["platform"]
_def_platform_prompt = _SENTINELS["platform_prompt"]
_def_voice = legacy._layer_voice(_SENTINELS["profile"], _SENTINELS["style"], _SENTINELS["trigger"])
_def_platform_layer = legacy._layer_platform(_def_platform, _def_platform_prompt)
_def_core = legacy._layer_core("info", _SENTINELS["keyword"])
_def_output = legacy._layer_output_spec(True, platform=_def_platform, mode="info")
_def_prompt, _ = legacy._build_prompt(
    keyword=_SENTINELS["keyword"],
    mode="info",
    profile=_SENTINELS["profile"],
    style=_SENTINELS["style"],
    trigger=_SENTINELS["trigger"],
    platform=_def_platform,
    platform_prompt=_def_platform_prompt,
    dynamics={
        "info_density": _SENTINELS["info_density"],
        "hesitation": _SENTINELS["hesitation"],
        "detail_level": _SENTINELS["detail_level"],
        "sentence_pattern": _SENTINELS["sentence_pattern"],
    },
)

_voice_index = _def_prompt.index(_def_voice)
_platform_index = _def_prompt.index(_def_platform_layer)
_core_index = _def_prompt.index(_def_core)
_output_index = _def_prompt.index(_def_output, _core_index + len(_def_core))

_header_text = _def_prompt[:_voice_index]
_header_text = _header_text.replace(f"{legacy.datetime.now().month}?", f"{_SENTINELS['current_month']}?")
HEADER_TEMPLATE = _to_template(_header_text, {"current_month": _SENTINELS["current_month"]})

_dynamic_text = _def_prompt[_voice_index + len(_def_voice) + 2:_platform_index - 2]
DYNAMIC_LAYER_TEMPLATE = _to_template(
    _dynamic_text,
    {
        "info_density": _SENTINELS["info_density"],
        "hesitation": _SENTINELS["hesitation"],
        "detail_level": _SENTINELS["detail_level"],
        "sentence_pattern": _SENTINELS["sentence_pattern"],
    },
)

_prompt_frame = _def_prompt
_prompt_frame = _prompt_frame.replace(_header_text, _SENTINELS["current_month"])
_prompt_frame = _prompt_frame.replace(_def_voice, _SENTINELS["voice"])
_prompt_frame = _prompt_frame.replace(_dynamic_text, _SENTINELS["dynamic_text"])
_prompt_frame = _prompt_frame.replace(_def_platform_layer, _SENTINELS["platform_layer"])
_prompt_frame = _prompt_frame.replace("info", _SENTINELS["mode"], 1)
_prompt_frame = _prompt_frame.replace(
    _def_core + "\n",
    _SENTINELS["core"] + "\n" + _SENTINELS["examples"],
    1,
)
_prompt_frame = _prompt_frame.replace(_def_output, _SENTINELS["output_spec"], 1)
PROMPT_FRAME_TEMPLATE = _to_template(
    _prompt_frame,
    {
        "current_month": _SENTINELS["current_month"],
        "voice": _SENTINELS["voice"],
        "dynamic_text": _SENTINELS["dynamic_text"],
        "platform_layer": _SENTINELS["platform_layer"],
        "mode": _SENTINELS["mode"],
        "core": _SENTINELS["core"],
        "examples": _SENTINELS["examples"],
        "output_spec": _SENTINELS["output_spec"],
    },
)


def render_core_layer(mode: str, keyword: str) -> str:
    return CORE_LAYER_TEMPLATES[mode].substitute(keyword=keyword)


def render_voice_layer(profile: str, style: str, trigger: str) -> str:
    return VOICE_LAYER_TEMPLATE.substitute(profile=profile, style=style, trigger=trigger)


def render_platform_layer(platform: str, platform_prompt: str) -> str:
    return PLATFORM_LAYER_TEMPLATE.substitute(platform=platform, platform_prompt=platform_prompt)


def render_dynamic_layer(dynamics: dict) -> str:
    return DYNAMIC_LAYER_TEMPLATE.substitute(**dynamics)


def render_prompt_frame(*, current_month: int, voice: str, dynamic_text: str, platform_layer: str, mode: str, core: str, examples: str, output_spec: str) -> str:
    header = HEADER_TEMPLATE.substitute(current_month=current_month)
    return PROMPT_FRAME_TEMPLATE.substitute(
        current_month=header,
        voice=voice,
        dynamic_text=dynamic_text,
        platform_layer=platform_layer,
        mode=mode,
        core=core,
        examples=examples,
        output_spec=output_spec,
    )
