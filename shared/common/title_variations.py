from config import BRAND


SOHU_TITLE_FALLBACKS = {
    "exp": [
        "{brand}就诊过程记录，说说我那次看完后的感受",
        "{brand}看诊经历整理，聊聊我这次就诊留下的印象",
        "{brand}这次就诊后的一点记录，说说我最在意的几个点",
    ],
    "default": [
        "{brand}实地了解了一下，说说我了解到的情况",
        "{brand}最近留意到一些情况，聊聊我整理下来的印象",
        "{brand}相关信息梳理了一下，说说我打听到的内容",
        "{brand}查了一圈本地信息，聊聊我最后记下来的重点",
    ],
}

SOHU_EXP_REPAIR_MARKERS = (
    "查到",
    "了解到的情况",
    "整理下来的印象",
)

SOHU_DEFAULT_REPEAT_VARIANTS = [
    "{brand}实地了解了一下，说说我打听到的信息",
    "{brand}最近留意到一些情况，聊聊我整理下来的印象",
    "{brand}相关信息梳理了一下，说说我了解到的内容",
    "{brand}顺手查了些本地反馈，聊聊我最后记下来的重点",
]

SOHU_DEFAULT_REPEAT_TEMPLATES = {
    "{brand}实地了解了一下，说说我了解到的情况",
    "{brand}实地了解了一下，说说我查到的情况",
}


def render_templates(templates) -> list[str]:
    return [template.format(brand=BRAND) for template in templates]
