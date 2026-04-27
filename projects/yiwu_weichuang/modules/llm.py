from openai import OpenAI
from config import MODEL_TYPE
from config import OPENAI_API_KEY, OPENAI_MAIN_MODEL, OPENAI_FAST_MODEL
from modules.logger import record_llm_call
from modules.llm_doubao import call_doubao
from modules.llm_packy import call_packy


def call_llm(prompt: str, fast: bool = False, provider: str = None,
             main_model: str = None, fast_model: str = None) -> str:
    """
    fast=False → 使用主模型（生成初稿）
    fast=True  → 使用快速模型（去AI化/评分），留空则自动回退到主模型
    """
    provider = provider or MODEL_TYPE

    if provider == "doubao":
        return call_doubao(prompt, fast=fast, main_model=main_model, fast_model=fast_model)
    elif provider == "packy":
        return call_packy(prompt, fast=fast, main_model=main_model, fast_model=fast_model)
    elif provider == "openai":
        return _call_openai(prompt, fast=fast, main_model=main_model, fast_model=fast_model)
    else:
        raise ValueError(f"未知 provider：{provider}")


def _call_openai(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> str:
    model = (fast_model or OPENAI_FAST_MODEL or main_model or OPENAI_MAIN_MODEL) if fast else (main_model or OPENAI_MAIN_MODEL)
    tier = f"openai:{'lite' if fast else 'pro'}"
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        usage = getattr(response, "usage", None)
        record_llm_call(
            tier=tier,
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        print(f"OpenAI调用失败（{'快速' if fast else '主'}模型）：", e)
        record_llm_call(
            tier=tier,
            model=model,
            prompt_tokens=None,
            completion_tokens=None,
            error=str(e),
        )
        return ""
