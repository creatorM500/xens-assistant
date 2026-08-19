"""Unit tests: descubrimiento LRU (ahorro de tokens) + run_any_tool.

Uso: python tests/test_tool_search.py  (desde la raÃ­z del repo)
"""
import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from xens_assistant.tools.registry import registry
from xens_assistant.tools import tool_search as ts


def test_lru_cap():
    ts._discovered_tools.clear()
    ts._discovery_order.clear()
    old_max = ts._MAX_DISCOVERED
    ts._MAX_DISCOVERED = 3
    try:
        evicted = ts._discover(["t1", "t2", "t3", "t4"])
        assert set(ts._discovered_tools) == {"t2", "t3", "t4"}, ts._discovered_tools
        assert evicted == ["t1"], evicted

        # usar t2 la reordena (LRU): el prÃ³ximo a salir es t3
        ts._touch("t2")
        evicted2 = ts._discover(["t5"])
        assert evicted2 == ["t3"], evicted2
        assert set(ts._discovered_tools) == {"t2", "t4", "t5"}, ts._discovered_tools

        # re-descubrir algo ya activo no duplica ni evicta
        evicted3 = ts._discover(["t2"])
        assert evicted3 == [] and set(ts._discovered_tools) == {"t2", "t4", "t5"}
    finally:
        ts._MAX_DISCOVERED = old_max
        ts._discovered_tools.clear()
        ts._discovery_order.clear()


async def test_run_any_tool():
    p_echo = {"type": "object", "properties": {"x": {"type": "integer", "description": "x"}}, "required": ["x"]}
    registry.register("_rat_echo", lambda x: json.dumps({"echo": x}), description="echo",
                      parameters=p_echo, tier="free")
    registry.register("_rat_pro_only", lambda: "pro", description="pro", tier="pro")

    # tier free: la tool free pasa, la pro queda bloqueada por tier
    registry.set_tier("free")
    out = json.loads(await ts.run_any_tool("_rat_echo", '{"x": 5}'))
    assert out == {"echo": 5}, out
    out2 = json.loads(await ts.run_any_tool("_rat_pro_only", "{}"))
    assert out2["success"] is False and "tier" in out2.get("error", ""), out2

    # JSON invÃ¡lido -> mensaje claro
    out3 = json.loads(await ts.run_any_tool("_rat_echo", "{mal"))
    assert out3["success"] is False and "JSON" in out3["error"], out3

    # tool inexistente
    out4 = json.loads(await ts.run_any_tool("_rat_no_existe", "{}"))
    assert out4["success"] is False, out4

    # con tier pro la tool pro ya se puede ejecutar
    registry.set_tier("pro")
    out5 = await ts.run_any_tool("_rat_pro_only", "{}")
    assert "pro" in out5, out5
    registry.set_tier("free")


def main():
    test_lru_cap()
    asyncio.run(test_run_any_tool())
    print("TOOL_SEARCH_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


