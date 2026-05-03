from config import BRAND, AUX_PROVIDER
from project_paths import prompt_path
from common.llm import call_llm_result



def expand_one(core_keyword: str) -> str:
    """单次扩展：从核心词生成一个具体的长尾搜索词（使用辅助模型快速链路）"""
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

    result = result.lstrip("0123456789.-、 ").strip('"""\'\'\'')
    result = result.replace("{品牌}", BRAND).replace("{brand}", BRAND)
    return result if 4 < len(result) < 50 else core_keyword
