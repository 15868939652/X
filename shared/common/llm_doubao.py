import httpx
from openai import OpenAI

from config import DOUBAO_API_KEY, DOUBAO_BASE_URL, DOUBAO_FAST_MODEL, DOUBAO_MAIN_MODEL

LLM_TIMEOUT_FAST = httpx.Timeout(120.0, connect=15.0, read=110.0, write=60.0)
LLM_TIMEOUT_PRO = httpx.Timeout(180.0, connect=15.0, read=170.0, write=60.0)


def request_doubao(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    model = (fast_model or DOUBAO_FAST_MODEL or main_model or DOUBAO_MAIN_MODEL) if fast else (main_model or DOUBAO_MAIN_MODEL)
    timeout = LLM_TIMEOUT_FAST if fast else LLM_TIMEOUT_PRO
    client = OpenAI(api_key=DOUBAO_API_KEY, base_url=DOUBAO_BASE_URL, timeout=timeout, max_retries=0)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,
        timeout=timeout,
    )
    usage = getattr(response, "usage", None)
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = getattr(message, "content", None) if message else ""
    return {
        "provider": "doubao",
        "model": model,
        "tier": f"doubao:{'lite' if fast else 'pro'}",
        "content": content or "",
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }
