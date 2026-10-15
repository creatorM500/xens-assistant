"""Unit tests: generate_image (registro + validación, sin red).

Uso: python -m pytest tests/test_image_gen.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.tools.registry import registry, discover_tools
from ainslup_assistant.tools import image_gen


def test_registered_with_prompt_param():
    discover_tools()
    schemas = registry.get_schemas_by_names(["generate_image"])
    assert schemas, "generate_image no registrada"
    s = schemas[0]
    params = (s.get("function", {}).get("parameters", {}) or {})
    assert "prompt" in (params.get("properties", {}) or {}), s
    assert "prompt" in (params.get("required", []) or []), s
    tool = registry._tools.get("generate_image")
    assert tool and tool.get("tier") == "free", tool


def test_empty_prompt_no_network():
    out = json.loads(image_gen.generate_image(""))
    assert out["success"] is False and "prompt" in out["error"].lower()


def test_model_aliases():
    assert image_gen._MODEL_ALIASES[""] == image_gen.FREE_MODEL
    assert image_gen._MODEL_ALIASES["flux"] == image_gen.PRO_MODEL


if __name__ == "__main__":
    test_registered_with_prompt_param()
    test_empty_prompt_no_network()
    test_model_aliases()
    print("IMAGE_GEN_OK")
