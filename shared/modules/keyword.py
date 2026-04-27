import os
from config import BRAND, AUX_PROVIDER
from modules.llm import call_llm


def expand_keywords(core_keyword: str, template: str) -> list:
    """批量扩展：从一个核心词扩展出多个长尾词（保留备用）"""
    prompt = template.replace("{核心词}", core_keyword).replace("{品牌}", BRAND)
    result = call_llm(prompt, provider=AUX_PROVIDER)

    keywords = []
    for line in result.split("\n"):
        line = line.strip()
        if len(line) > 4:
            keywords.append(line)

    return list(set(keywords))


def expand_one(core_keyword: str) -> str:
    """单次扩展：从核心词生成一个具体的长尾搜索词（使用辅助模型快速链路）"""
    path = os.path.join("prompts", "keyword_expand_one.txt")
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{核心词}", core_keyword)
        .replace("{品牌}", BRAND)
    )
    result = call_llm(prompt, fast=True, provider=AUX_PROVIDER).strip()

    # 清理编号、引号等多余字符
    result = result.lstrip("0123456789.-、 ").strip('"""\'\'\'')

    # 若 LLM 仍然漏填占位符，做一次 defensive 替换
    result = result.replace("{品牌}", BRAND).replace("{brand}", BRAND)

    # 若结果明显异常则回退到核心词本身
    return result if 4 < len(result) < 50 else core_keyword
