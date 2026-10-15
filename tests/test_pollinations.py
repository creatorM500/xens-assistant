"""Unit tests: segundo cerebro gratis (Pollinations deepseek-v3.2 community).

Sin red: solo defaults, factory, creditos y tier defaults.
Uso: python -m pytest tests/test_pollinations.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.llm.factory import create_provider
from ainslup_assistant.llm.openai import OpenAIProvider
from ainslup_assistant.core import credits as cred_mod
from ainslup_assistant.core.model_router import _model_role
from ainslup_assistant.core.tier_config import DEFAULT_CONFIG

POLLI_MODEL = "community/vendouple/deepseek-v3.2"


def test_provider_defaults():
    p = OpenAIProvider({"llm": {"pollinations": {"api_key": "fake"}}}, section="pollinations")
    assert str(p._client.base_url).rstrip("/") == "https://gen.pollinations.ai/v1", p._client.base_url
    assert p._model == POLLI_MODEL, p._model


def test_factory_loads_pollinations():
    tp = create_provider({"llm": {"pollinations": {"api_key": "fake"}}})
    assert "pollinations" in tp._providers, sorted(tp._providers)


def test_factory_skips_without_key():
    tp = create_provider({"llm": {"openrouter": {"api_key": "fake-or"}}})
    assert "pollinations" not in tp._providers, sorted(tp._providers)


def test_credits_and_role():
    assert cred_mod.model_multiplier(POLLI_MODEL) == 0.5
    assert _model_role(POLLI_MODEL) == "cheap"


def test_free_tier_lists_pollinations_first():
    models = DEFAULT_CONFIG["free"]["models"]
    assert models[0]["provider"] == "pollinations", models[0]
    assert models[0]["model"] == POLLI_MODEL, models[0]


if __name__ == "__main__":
    test_provider_defaults()
    test_factory_loads_pollinations()
    test_factory_skips_without_key()
    test_credits_and_role()
    test_free_tier_lists_pollinations_first()
    print("POLLINATIONS_OK")
