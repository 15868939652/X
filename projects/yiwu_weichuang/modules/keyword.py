from project_paths import prompt_path
from config import BRAND, AUX_PROVIDER
from common.llm import call_llm_result
from modules.profile_loader import get_other_brand_aliases


_FOREIGN_BRAND_ALIASES = tuple(get_other_brand_aliases())


def _normalize_brand_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("{品牌}", BRAND).replace("{brand}", BRAND)
    for alias in _FOREIGN_BRAND_ALIASES:
        if alias and alias in text:
            text = text.replace(alias, BRAND)
    return text



def expand_one(core_keyword: str) -> str:
    path = prompt_path("keyword_expand_one.txt")
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{核心词}", core_keyword)
        .replace("{品牌}", BRAND)
    )
    llm_result = call_llm_result(prompt, fast=True, provider=AUX_PROVIDER, retries=1, stage="keyword_expand_one")
    if llm_result.failed or llm_result.empty:
        return core_keyword
    result = llm_result.content.strip()
    result = result.lstrip("0123456789.-、").strip('"""\'\'\'')
    result = _normalize_brand_text(result)

    return result if 4 < len(result) < 50 else core_keyword
