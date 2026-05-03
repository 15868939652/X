import time
import threading
from dataclasses import dataclass, field

import httpx
from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_FAST_MODEL,
    DEEPSEEK_MAIN_MODEL,
    DOUBAO_API_KEY,
    GLM_API_KEY,
    GLM_BASE_URL,
    GLM_FAST_MODEL,
    GLM_MAIN_MODEL,
    LLM_MAX_CONCURRENT,
    MODEL_TYPE,
    OPENAI_API_KEY,
    OPENAI_FAST_MODEL,
    OPENAI_MAIN_MODEL,
    PACKY_API_KEY,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_FAST_MODEL,
    QWEN_MAIN_MODEL,
)
from common.llm_doubao import request_doubao
from common.llm_packy import request_packy
from common.logger import record_llm_call

RETRY_BACKOFF_SECONDS = (1, 2, 4)
LLM_TIMEOUT_FAST = httpx.Timeout(120.0, connect=15.0, read=110.0, write=60.0)
LLM_TIMEOUT_PRO = httpx.Timeout(180.0, connect=15.0, read=170.0, write=60.0)
LLM_CONCURRENCY_LIMIT = max(1, int(LLM_MAX_CONCURRENT))
_LLM_SEMAPHORE = threading.BoundedSemaphore(LLM_CONCURRENCY_LIMIT)


class LLMCallError(RuntimeError):
    pass


@dataclass
class LLMCallResult:
    content: str
    provider: str
    model: str
    tier: str
    status: str
    attempts: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def empty(self) -> bool:
        return self.status == "empty"

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _request_openai(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    model = (fast_model or OPENAI_FAST_MODEL or main_model or OPENAI_MAIN_MODEL) if fast else (main_model or OPENAI_MAIN_MODEL)
    timeout = LLM_TIMEOUT_FAST if fast else LLM_TIMEOUT_PRO
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=timeout, max_retries=0)
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
        "provider": "openai",
        "model": model,
        "tier": f"openai:{'lite' if fast else 'pro'}",
        "content": content or "",
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }


def _request_compatible(
    prompt: str,
    *,
    provider: str,
    api_key: str,
    base_url: str,
    default_main_model: str,
    default_fast_model: str,
    fast: bool = False,
    main_model: str = None,
    fast_model: str = None,
) -> dict:
    model = (fast_model or default_fast_model or main_model or default_main_model) if fast else (main_model or default_main_model)
    timeout = LLM_TIMEOUT_FAST if fast else LLM_TIMEOUT_PRO
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3 if provider == "glm" else 0.85,
        timeout=timeout,
    )
    usage = getattr(response, "usage", None)
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = getattr(message, "content", None) if message else ""
    return {
        "provider": provider,
        "model": model,
        "tier": f"{provider}:{'lite' if fast else 'pro'}",
        "content": content or "",
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }


def _request_qwen(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    return _request_compatible(
        prompt,
        provider="qwen",
        api_key=QWEN_API_KEY,
        base_url=QWEN_BASE_URL,
        default_main_model=QWEN_MAIN_MODEL,
        default_fast_model=QWEN_FAST_MODEL,
        fast=fast,
        main_model=main_model,
        fast_model=fast_model,
    )


def _request_glm(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    return _request_compatible(
        prompt,
        provider="glm",
        api_key=GLM_API_KEY,
        base_url=GLM_BASE_URL,
        default_main_model=GLM_MAIN_MODEL,
        default_fast_model=GLM_FAST_MODEL,
        fast=fast,
        main_model=main_model,
        fast_model=fast_model,
    )


def _request_deepseek(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    return _request_compatible(
        prompt,
        provider="deepseek",
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        default_main_model=DEEPSEEK_MAIN_MODEL,
        default_fast_model=DEEPSEEK_FAST_MODEL,
        fast=fast,
        main_model=main_model,
        fast_model=fast_model,
    )


_PROVIDER_HANDLERS = {
    "deepseek": _request_deepseek,
    "doubao": request_doubao,
    "glm": _request_glm,
    "packy": request_packy,
    "qwen": _request_qwen,
    "openai": _request_openai,
}

_PROVIDER_KEYS = {
    "deepseek": DEEPSEEK_API_KEY,
    "doubao": DOUBAO_API_KEY,
    "glm": GLM_API_KEY,
    "packy": PACKY_API_KEY,
    "qwen": QWEN_API_KEY,
    "openai": OPENAI_API_KEY,
}

_PLACEHOLDER_KEYS = {
    "",
    "your_openai_api_key_here",
    "your_packy_api_key_here",
    "your_doubao_api_key_here",
    "your_deepseek_api_key_here",
    "your_qwen_api_key_here",
    "your_glm_api_key_here",
}


def _provider_label(provider: str) -> str:
    return {
        "doubao": "豆包",
        "packy": "Packy",
        "openai": "OpenAI",
    }.get(provider, provider)


def _provider_key_missing(provider: str) -> bool:
    return (_PROVIDER_KEYS.get(provider) or "").strip() in _PLACEHOLDER_KEYS


def _looks_like_auth_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "401",
            "unauthorized",
            "authentication",
            "invalid api key",
            "incorrect api key",
            "invalid_api_key",
            "鉴权",
            "未授权",
        )
    )


def _record_attempt(result: dict, *, error: str = "", attempt: int, max_attempts: int, status: str, latency_ms: int, stage: str = "") -> None:
    record_llm_call(
        tier=result["tier"],
        model=result["model"],
        provider=result["provider"],
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
        error=error or None,
        attempt=attempt,
        max_attempts=max_attempts,
        status=status,
        latency_ms=latency_ms,
        stage=stage,
    )


def call_llm_result(
    prompt: str,
    fast: bool = False,
    provider: str = None,
    main_model: str = None,
    fast_model: str = None,
    retries: int | None = None,
    stage: str = "",
) -> LLMCallResult:
    provider = provider or MODEL_TYPE
    handler = _PROVIDER_HANDLERS.get(provider)
    if handler is None:
        raise ValueError(f"Unknown provider: {provider}")
    if _provider_key_missing(provider):
        message = f"{_provider_label(provider)} API Key 未配置，请检查 shared/config_base.py"
        return LLMCallResult(
            content="",
            provider=provider,
            model=main_model or "",
            tier=f"{provider}:{'lite' if fast else 'pro'}",
            status="failed",
            attempts=0,
            error=message,
            errors=[message],
        )

    retry_count = len(RETRY_BACKOFF_SECONDS) if retries is None else max(0, retries)
    max_attempts = 1 + retry_count
    errors: list[str] = []
    fallback_model = main_model or ""
    fallback_tier = f"{provider}:{'lite' if fast else 'pro'}"

    for attempt in range(1, max_attempts + 1):
        started_at = time.perf_counter()
        try:
            with _LLM_SEMAPHORE:
                response = handler(prompt, fast=fast, main_model=main_model, fast_model=fast_model)
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            status = "ok" if (response.get("content") or "").strip() else "empty"
            _record_attempt(
                response,
                attempt=attempt,
                max_attempts=max_attempts,
                status=status,
                latency_ms=latency_ms,
                stage=stage,
            )
            return LLMCallResult(
                content=response.get("content", ""),
                provider=response["provider"],
                model=response["model"],
                tier=response["tier"],
                status=status,
                attempts=attempt,
                prompt_tokens=response.get("prompt_tokens"),
                completion_tokens=response.get("completion_tokens"),
                errors=errors,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            message = str(exc).strip() or exc.__class__.__name__
            errors.append(message)
            print(f"[LLM] {provider} attempt {attempt}/{max_attempts} failed: {message}")
            error_response = {
                "provider": provider,
                "model": fallback_model,
                "tier": fallback_tier,
            }
            _record_attempt(
                error_response,
                error=message,
                attempt=attempt,
                max_attempts=max_attempts,
                status="failed",
                latency_ms=latency_ms,
                stage=stage,
            )
            if attempt >= max_attempts:
                return LLMCallResult(
                    content="",
                    provider=provider,
                    model=fallback_model,
                    tier=fallback_tier,
                    status="failed",
                    attempts=attempt,
                    error=message,
                    errors=errors,
                )
            if _looks_like_auth_error(message):
                auth_message = (
                    f"{_provider_label(provider)} 接口鉴权失败（401）。"
                    f"请检查 shared/config_base.py 中的 API Key 是否有效、是否已过期，"
                    f"以及当前账号是否有模型调用权限。原始错误：{message}"
                )
                print(f"[LLM] {provider} authentication failed, stop retrying.")
                return LLMCallResult(
                    content="",
                    provider=provider,
                    model=fallback_model,
                    tier=fallback_tier,
                    status="failed",
                    attempts=attempt,
                    error=auth_message,
                    errors=errors,
                )
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])

    return LLMCallResult(
        content="",
        provider=provider,
        model=fallback_model,
        tier=fallback_tier,
        status="failed",
        attempts=max_attempts,
        error=errors[-1] if errors else "unknown error",
        errors=errors,
    )


def call_llm(prompt: str, fast: bool = False, provider: str = None, main_model: str = None, fast_model: str = None) -> str:
    return call_llm_result(
        prompt,
        fast=fast,
        provider=provider,
        main_model=main_model,
        fast_model=fast_model,
    ).content


def require_llm_content(
    prompt: str,
    *,
    fast: bool = False,
    provider: str = None,
    main_model: str = None,
    fast_model: str = None,
    empty_error: str = "LLM returned empty content",
    stage: str = "",
) -> str:
    result = call_llm_result(
        prompt,
        fast=fast,
        provider=provider,
        main_model=main_model,
        fast_model=fast_model,
        stage=stage,
    )
    if result.failed:
        raise LLMCallError(result.error or f"{result.provider} 调用失败")
    if result.empty:
        raise LLMCallError(empty_error)
    return result.content
