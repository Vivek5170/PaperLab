"""Central pipeline configuration.

Import this module FIRST in every entry point (before ``database``,
``directory_manager``, or any tool module)::

    import config  # noqa: F401 -- pins env as a side effect
    import database
    import tools_indexer

Importing ``config`` resolves ``config.yaml`` (plus ``.env`` next to it for
secrets) and pins ``PHYSICS_ARCHIVE_DB`` / ``PHYSICS_OUTPUT_BASE`` in
``os.environ`` (without overriding explicitly set variables), so all
subsequently imported modules bind to the same database file and Outputs
tree.

Precedence: explicit env vars > ``config.yaml`` (+ ``.env`` for secrets) >
built-in defaults. The API key lives ONLY in the environment (``.env`` file
or real env) -- it is never written to yaml and never logged.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

CONFIG_PATH = Path(os.environ.get("PIPELINE_CONFIG", Path(__file__).parent / "config.yaml"))

# Load secrets first so yaml/env resolution below can see them.
load_dotenv(CONFIG_PATH.parent / ".env")

_DEFAULTS = {
    "database_path": "./physics_archive.db",
    "outputs_dir": "./Outputs",
    "llm": {
        "model": "muse-spark-1.3-contributor",
        "base_url": "https://api.meta.ai/v1",
        "use_responses_api": False,
        "reasoning_effort": "low",
    },
}


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        if os.environ.get("PIPELINE_CONFIG"):
            raise FileNotFoundError(f"Pipeline config not found: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Pipeline config must be a mapping: {path}")
    return data


def _resolve(raw: str) -> str:
    p = Path(raw)
    if not p.is_absolute():
        p = CONFIG_PATH.parent / p
    return str(p)


_raw = {**_DEFAULTS, **_load_yaml(CONFIG_PATH)}
_llm = {**_DEFAULTS["llm"], **(_raw.get("llm") or {})}

ARCHIVE_DB: str = os.environ.get(
    "PHYSICS_ARCHIVE_DB", _resolve(str(_raw["database_path"]))
)
OUTPUT_BASE: str = os.environ.get(
    "PHYSICS_OUTPUT_BASE", _resolve(str(_raw["outputs_dir"]))
)

# LLM wiring for the LangGraph agents (langchain-openai ChatOpenAI:
# model_name=LLM_MODEL, openai_api_base=LLM_BASE_URL,
# openai_api_key=LLM_API_KEY, use_responses_api=LLM_USE_RESPONSES_API).
LLM_MODEL: str = os.environ.get("LLM_MODEL", str(_llm["model"]))
LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", str(_llm["base_url"]))
LLM_USE_RESPONSES_API: bool = (
    os.environ.get("LLM_USE_RESPONSES_API", str(_llm["use_responses_api"])).lower()
    == "true"
)
LLM_REASONING_EFFORT: str | None = os.environ.get(
    "LLM_REASONING_EFFORT", str(_llm.get("reasoning_effort", "") or "")
) or None
LLM_API_KEY: str | None = os.environ.get("META_API_KEY")

# Pin for subsequently imported modules (setdefault: explicit env wins).
os.environ.setdefault("PHYSICS_ARCHIVE_DB", ARCHIVE_DB)
os.environ.setdefault("PHYSICS_OUTPUT_BASE", OUTPUT_BASE)


def as_dict() -> dict:
    """Resolved settings for startup logging / assertions (never the key)."""
    return {
        "config_file": str(CONFIG_PATH),
        "database_path": ARCHIVE_DB,
        "outputs_dir": OUTPUT_BASE,
        "llm_model": LLM_MODEL,
        "llm_base_url": LLM_BASE_URL,
        "llm_use_responses_api": LLM_USE_RESPONSES_API,
        "llm_reasoning_effort": LLM_REASONING_EFFORT,
        "llm_api_key_set": LLM_API_KEY is not None,
    }
