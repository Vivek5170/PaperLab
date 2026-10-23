"""LLM factory for the LangGraph agents (Phase 1 now, Phase 2 later).

Single construction point so every node shares one model/endpoint config,
read from config.py (config.yaml > env > defaults; key from .env).
"""

from __future__ import annotations

import config
from langchain_openai import ChatOpenAI


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
