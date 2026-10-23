"""Config tests: yaml resolution, precedence, and env pinning."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PINNED_KEYS = ("PHYSICS_ARCHIVE_DB", "PHYSICS_OUTPUT_BASE", "PIPELINE_CONFIG",
               "META_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_USE_RESPONSES_API",
               "LLM_REASONING_EFFORT", "LLM_RETRY_MAX_ATTEMPTS", "LLM_RETRY_BASE_SEC",
               "LLM_RETRY_BUDGET_SEC", "PRICE_INPUT", "PRICE_CACHE_READ",
               "PRICE_OUTPUT", "CURRENCY_DEFAULT", "USD_TO_INR")


def _load_fresh(monkeypatch, tmp_path, yaml_text=None, extra_env=None):
    """Exec a pristine copy of config.py under controlled env; restore env after.

    Uses a separate module name so sys.modules['config'] is never disturbed.
    """
    saved = dict(os.environ)
    try:
        for k in PINNED_KEYS:
            monkeypatch.delenv(k, raising=False)
        for k, v in (extra_env or {}).items():
            monkeypatch.setenv(k, v)
        if yaml_text is not None:
            cfg = tmp_path / "config.yaml"
            cfg.write_text(yaml_text, encoding="utf-8")
            monkeypatch.setenv("PIPELINE_CONFIG", str(cfg))
        spec = importlib.util.spec_from_file_location(
            "config_under_test", str(ROOT / "config.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pinned = {
            "PHYSICS_ARCHIVE_DB": os.environ.get("PHYSICS_ARCHIVE_DB"),
            "PHYSICS_OUTPUT_BASE": os.environ.get("PHYSICS_OUTPUT_BASE"),
        }
        return mod, pinned
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_yaml_values_used_and_resolved_relative(tmp_path, monkeypatch):
    mod, pinned = _load_fresh(
        monkeypatch, tmp_path,
        "database_path: ./db/a.db\noutputs_dir: ./out\n",
    )
    assert mod.ARCHIVE_DB == str(tmp_path / "db" / "a.db")
    assert mod.OUTPUT_BASE == str(tmp_path / "out")
    assert pinned["PHYSICS_ARCHIVE_DB"] == mod.ARCHIVE_DB
    assert pinned["PHYSICS_OUTPUT_BASE"] == mod.OUTPUT_BASE


def test_explicit_env_beats_yaml(tmp_path, monkeypatch):
    mod, _ = _load_fresh(
        monkeypatch, tmp_path,
        "database_path: ./db/a.db\noutputs_dir: ./out\n",
        extra_env={"PHYSICS_ARCHIVE_DB": "/env/override.db"},
    )
    assert mod.ARCHIVE_DB == "/env/override.db"
    assert mod.OUTPUT_BASE == str(tmp_path / "out")


def test_defaults_without_yaml(tmp_path, monkeypatch):
    mod, _ = _load_fresh(monkeypatch, tmp_path)
    assert mod.ARCHIVE_DB.endswith("physics_archive.db")
    assert mod.OUTPUT_BASE.endswith("Outputs")
    assert set(mod.as_dict()) == {"config_file", "database_path", "outputs_dir",
                                  "llm_model", "llm_base_url",
                                  "llm_use_responses_api", "llm_reasoning_effort",
                                  "llm_api_key_set", "llm_retry_max_attempts",
                                  "llm_retry_base_sec", "llm_retry_budget_sec",
                                  "pricing",
                                  "currency_default", "usd_to_inr"}
    assert mod.LLM_REASONING_EFFORT == "low"
    assert mod.CURRENCY_DEFAULT == "INR"
    assert mod.USD_TO_INR == 95.0


def test_currency_yaml_and_env_override(tmp_path, monkeypatch):
    mod, _ = _load_fresh(
        monkeypatch, tmp_path,
        "currency:\n  default: USD\n  usd_to_inr: 80.0\n",
    )
    assert mod.CURRENCY_DEFAULT == "USD"
    assert mod.USD_TO_INR == 80.0
    mod2, _ = _load_fresh(
        monkeypatch, tmp_path,
        "currency:\n  default: USD\n  usd_to_inr: 80.0\n",
        extra_env={"CURRENCY_DEFAULT": "INR", "USD_TO_INR": "90.5"},
    )
    assert mod2.CURRENCY_DEFAULT == "INR"
    assert mod2.USD_TO_INR == 90.5


def test_explicit_missing_config_errors(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        _load_fresh(
            monkeypatch, tmp_path,
            extra_env={"PIPELINE_CONFIG": str(tmp_path / "nope.yaml")},
        )


def test_llm_defaults_from_yaml(tmp_path, monkeypatch):
    mod, _ = _load_fresh(
        monkeypatch, tmp_path,
        "database_path: ./db/a.db\noutputs_dir: ./out\n"
        "llm:\n  model: muse-spark-1.3-contributor\n"
        "  base_url: https://api.meta.ai/v1\n  use_responses_api: false\n",
    )
    assert mod.LLM_MODEL == "muse-spark-1.3-contributor"
    assert mod.LLM_BASE_URL == "https://api.meta.ai/v1"
    assert mod.LLM_USE_RESPONSES_API is False
    assert mod.LLM_API_KEY is None  # no key anywhere -> None, never crash


def test_llm_env_overrides_yaml(tmp_path, monkeypatch):
    mod, _ = _load_fresh(
        monkeypatch, tmp_path,
        "llm:\n  model: yaml-model\n  base_url: https://yaml.example/v1\n",
        extra_env={"LLM_MODEL": "env-model", "META_API_KEY": "sk-test",
                   "LLM_USE_RESPONSES_API": "true",
                   "LLM_REASONING_EFFORT": "high"},
    )
    assert mod.LLM_MODEL == "env-model"
    assert mod.LLM_BASE_URL == "https://yaml.example/v1"
    assert mod.LLM_USE_RESPONSES_API is True
    assert mod.LLM_REASONING_EFFORT == "high"
    assert mod.LLM_API_KEY == "sk-test"


def test_as_dict_never_leaks_key(tmp_path, monkeypatch):
    mod, _ = _load_fresh(
        monkeypatch, tmp_path,
        extra_env={"META_API_KEY": "sk-super-secret"},
    )
    dumped = str(mod.as_dict())
    assert "sk-super-secret" not in dumped
    assert mod.as_dict()["llm_api_key_set"] is True


def test_retry_defaults_and_overrides(tmp_path, monkeypatch):
    mod, _ = _load_fresh(monkeypatch, tmp_path)
    assert (mod.LLM_RETRY_MAX_ATTEMPTS, mod.LLM_RETRY_BASE_SEC,
            mod.LLM_RETRY_BUDGET_SEC) == (8, 2.0, 300.0)
    mod2, _ = _load_fresh(
        monkeypatch, tmp_path,
        "llm:\n  retry_max_attempts: 3\n  retry_base_sec: 0.5\n"
        "  retry_budget_sec: 60.0\n",
        extra_env={"LLM_RETRY_MAX_ATTEMPTS": "5"},
    )
    assert mod2.LLM_RETRY_MAX_ATTEMPTS == 5  # env beats yaml
    assert mod2.LLM_RETRY_BASE_SEC == 0.5
    assert mod2.LLM_RETRY_BUDGET_SEC == 60.0
