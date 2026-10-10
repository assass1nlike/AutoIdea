"""Tests for the independent reviewer/judge model (P0-3).

Covers:
  - LLMClient.reviewer_from_rc_config factory (None / same-endpoint / independent)
  - build_reviewer_llm helper (acp + unset => None)
  - config parsing of reviewer_* fields
  - review-stage routing & provenance (Stage 18 peer review, Stage 20 gate helper)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from researchclaw.config import LlmConfig, RCConfig
from researchclaw.llm.client import LLMClient
from researchclaw.llm import build_reviewer_llm


def _make_rc_config(provider: str = "openai-compatible", **llm_kwargs):
    """Lightweight RCConfig stand-in.

    The reviewer factory and review stages only read ``config.llm.*`` and
    ``config.research.topic``, so a SimpleNamespace avoids RCConfig's many
    required sub-configs.
    """
    from types import SimpleNamespace

    llm = LlmConfig(provider=provider, **llm_kwargs)
    return SimpleNamespace(llm=llm, research=SimpleNamespace(topic="t"))


# --------------------------------------------------------------------------
# Factory: reviewer_from_rc_config
# --------------------------------------------------------------------------

def test_reviewer_none_when_unset() -> None:
    cfg = _make_rc_config(primary_model="gpt-4o", base_url="https://x/v1", api_key="k")
    assert LLMClient.reviewer_from_rc_config(cfg) is None
    assert build_reviewer_llm(cfg) is None


def test_reviewer_same_endpoint_different_model() -> None:
    cfg = _make_rc_config(
        primary_model="gpt-4o",
        base_url="https://main/v1",
        api_key="mainkey",
        reviewer_model="claude-sonnet-4-6",
        reasoning_effort="xhigh",
    )
    rc = LLMClient.reviewer_from_rc_config(cfg)
    assert rc is not None
    # Different model, but reuses the main endpoint/key.
    assert rc.config.primary_model == "claude-sonnet-4-6"
    assert rc.config.base_url == "https://main/v1"
    assert rc.config.api_key == "mainkey"
    assert rc.config.reasoning_effort == "xhigh"
    # Reviewer never falls back to the author model.
    assert list(rc.config.fallback_models) == []


def test_reviewer_fully_independent_provider() -> None:
    # Use a plain OpenAI-compatible provider so the unit test never constructs a
    # provider adapter that might touch the network.
    cfg = _make_rc_config(
        primary_model="gpt-4o",
        base_url="https://main/v1",
        api_key="mainkey",
        reviewer_model="some-other-model",
        reviewer_provider="openai-compatible",
        reviewer_base_url="https://rev/v1",
        reviewer_api_key="revkey",
    )
    rc = LLMClient.reviewer_from_rc_config(cfg)
    assert rc is not None
    assert rc.config.primary_model == "some-other-model"
    assert rc.config.base_url == "https://rev/v1"
    assert rc.config.api_key == "revkey"


def test_reviewer_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWER_KEY", "fromenv")
    cfg = _make_rc_config(
        primary_model="gpt-4o",
        base_url="https://main/v1",
        api_key="mainkey",
        reviewer_model="m2",
        reviewer_api_key_env="REVIEWER_KEY",
    )
    rc = LLMClient.reviewer_from_rc_config(cfg)
    assert rc is not None
    assert rc.config.api_key == "fromenv"


def test_build_reviewer_llm_none_for_acp() -> None:
    cfg = _make_rc_config(provider="acp", reviewer_model="whatever")
    assert build_reviewer_llm(cfg) is None


# --------------------------------------------------------------------------
# Config parsing
# --------------------------------------------------------------------------

def test_parse_reviewer_fields() -> None:
    from researchclaw.config import _parse_llm_config

    cfg = _parse_llm_config(
        {
            "provider": "openai-compatible",
            "primary_model": "gpt-4o",
            "reviewer_model": "claude-sonnet-4-6",
            "reviewer_provider": "anthropic",
            "reviewer_base_url": "https://rev/v1",
            "reviewer_api_key_env": "ANTHROPIC_API_KEY",
        }
    )
    assert cfg.reviewer_model == "claude-sonnet-4-6"
    assert cfg.reviewer_provider == "anthropic"
    assert cfg.reviewer_base_url == "https://rev/v1"
    assert cfg.reviewer_api_key_env == "ANTHROPIC_API_KEY"


def test_parse_reviewer_defaults_empty() -> None:
    from researchclaw.config import _parse_llm_config

    cfg = _parse_llm_config({"provider": "openai", "primary_model": "gpt-4o"})
    assert cfg.reviewer_model == ""
    assert cfg.reviewer_provider == ""


# --------------------------------------------------------------------------
# Review-stage routing & provenance
# --------------------------------------------------------------------------
