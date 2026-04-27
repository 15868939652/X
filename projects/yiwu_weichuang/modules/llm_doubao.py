from openai import OpenAI
from config import DOUBAO_API_KEY, DOUBAO_BASE_URL, DOUBAO_MAIN_MODEL, DOUBAO_FAST_MODEL
from modules.logger import record_llm_call


def call_doubao(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> str:
    model = (fast_model or DOUBAO_FAST_MODEL or main_model or DOUBAO_MAIN_MODEL) if fast else (main_model or DOUBAO_MAIN_MODEL)
    tier = f"doubao:{'lite' if fast else 'pro'}"

    try:
        client = OpenAI(api_key=DOUBAO_API_KEY, base_url=DOUBAO_BASE_URL)
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
        print(f"豆包调用失败（{'快速' if fast else '主'}模型）：", e)
        record_llm_call(
            tier=tier,
            model=model,
            prompt_tokens=None,
            completion_tokens=None,
            error=str(e),
        )
        return ""
