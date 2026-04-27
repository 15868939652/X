from openai import OpenAI
from config import PACKY_API_KEY, PACKY_BASE_URL, PACKY_MAIN_MODEL, PACKY_FAST_MODEL
from modules.logger import record_llm_call


def call_packy(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> str:
    model = (fast_model or PACKY_FAST_MODEL or main_model or PACKY_MAIN_MODEL) if fast else (main_model or PACKY_MAIN_MODEL)
    tier = f"packy:{'lite' if fast else 'pro'}"

    try:
        client = OpenAI(api_key=PACKY_API_KEY, base_url=PACKY_BASE_URL)
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

        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if not message:
            return ""
        content = getattr(message, "content", None)
        return content or ""
    except Exception as e:
        print(f"Packy调用失败（{'快速' if fast else '主'}模型）：", e)
        record_llm_call(
            tier=tier,
            model=model,
            prompt_tokens=None,
            completion_tokens=None,
            error=str(e),
        )
        return ""
