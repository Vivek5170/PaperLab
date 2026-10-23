"""LLM factory for the LangGraph agents (Phase 1 now, Phase 2 later).

Single construction point so every node shares one model/endpoint config,
read from config.py (config.yaml > env > defaults; key from .env).

All model calls should go through :func:`invoke_with_retry`, which rides
out rate limits (429) and transient 5xx/timeouts with exponential backoff
inside a ~5-minute total budget, then re-raises. Non-retryable errors
(auth, bad request, ...) fail fast on the first attempt.
"""

from __future__ import annotations

import random
import time

import config
from langchain_openai import ChatOpenAI

# Goal: absorb a rate-limit storm without failing the run. Worst case with
# defaults: 2+4+8+16+32+64+128 = 254s of waiting across 8 attempts, inside
# the 300s cumulative budget (a large Retry-After is clamped to it).
_PER_WAIT_CAP_SEC = 120.0
_RETRYABLE_STATUS = {408, 425, 429} | set(range(500, 600))
_RETRYABLE_NAMES = frozenset({
    "RateLimitError", "APITimeoutError", "APIConnectionError",
    "InternalServerError", "ServiceUnavailableError", "TimeoutError",
    "ConnectError", "ReadTimeout", "PoolTimeout",
})


def get_llm() -> ChatOpenAI:
    """Build the ChatOpenAI client for Muse Spark 1.3.

    Raises:
        RuntimeError: If META_API_KEY is missing/placeholder (fill in .env).
    """
    if not config.LLM_API_KEY or "paste-your-key" in config.LLM_API_KEY:
        raise RuntimeError(
            "META_API_KEY is missing or still a placeholder -- "
            "copy .env.example to .env and paste your key."
        )
    return ChatOpenAI(
        model_name=config.LLM_MODEL,
        openai_api_base=config.LLM_BASE_URL,
        openai_api_key=config.LLM_API_KEY,
        use_responses_api=config.LLM_USE_RESPONSES_API,
        reasoning_effort=config.LLM_REASONING_EFFORT,
        temperature=0,
    )


def _is_retryable(exc: BaseException) -> bool:
    """True for rate limits and transient server/network errors only."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS:
        return True
    try:  # isinstance layer for timeouts/connection drops without a code
        import openai as _openai

        if isinstance(
            exc,
            (
                _openai.RateLimitError,
                _openai.APITimeoutError,
                _openai.APIConnectionError,
                _openai.InternalServerError,
            ),
        ):
            return True
    except ImportError:
        pass
    return type(exc).__name__ in _RETRYABLE_NAMES


def _retry_after_sec(exc: BaseException, default: float) -> float:
    """Honor a server Retry-After hint, defensively (never raises)."""
    try:
        resp = getattr(exc, "response", None)
        headers = getattr(resp, "headers", None) or {}
        hint = headers.get("retry-after") if hasattr(headers, "get") else None
        if hint is None:
            hint = getattr(exc, "retry_after", None)
        if hint is not None:
            return max(default, min(float(hint), _PER_WAIT_CAP_SEC))
    except (TypeError, ValueError):
        pass
    return default


def invoke_with_retry(
    llm,
    messages,
    max_attempts: int | None = None,
    base_sec: float | None = None,
    budget_sec: float | None = None,
    _sleep=time.sleep,
):
    """Invoke the model, retrying rate limits/transients with backoff.

    Waits double from ``base_sec`` per retry (plus small jitter), capped per
    wait, inside a cumulative ``budget_sec`` ceiling (~5 min by default).
    Re-raises the last error when attempts or budget run out; non-retryable
    errors raise immediately. ``_sleep`` is injectable for tests.
    """
    attempts = int(max_attempts if max_attempts is not None
                   else config.LLM_RETRY_MAX_ATTEMPTS)
    base = float(base_sec if base_sec is not None else config.LLM_RETRY_BASE_SEC)
    budget = float(budget_sec if budget_sec is not None
                   else config.LLM_RETRY_BUDGET_SEC)
    spent = 0.0
    last: BaseException | None = None
    for i in range(1, attempts + 1):
        try:
            return llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 -- classified below
            last = exc
            if not _is_retryable(exc) or i == attempts:
                raise
            wait = min(base * 2 ** (i - 1), _PER_WAIT_CAP_SEC)
            wait = _retry_after_sec(exc, wait) + random.uniform(0, 1.0)
            remaining = budget - spent
            if remaining <= 0:
                raise
            wait = min(wait, remaining)
            print(f"[llm retry {i}/{attempts}] {type(exc).__name__}: "
                  f"waiting {wait:.1f}s (budget left {remaining:.0f}s)")
            _sleep(wait)
            spent += wait
    raise last  # unreachable; keeps type-checkers honest
