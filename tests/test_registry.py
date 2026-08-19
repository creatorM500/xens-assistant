import json
import pytest
from xens_assistant.tools.registry import ToolRegistry


def make_registry():
    return ToolRegistry()


def test_register_and_retrieve():
    r = make_registry()

    def my_tool(name: str) -> str:
        return f"hello {name}"

    r.register("greet", my_tool, "A greeting tool", {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    })

    assert "greet" in r._tools
    assert r.count == 1


def test_get_schemas():
    r = make_registry()

    def my_tool(name: str) -> str:
        return f"hello {name}"

    r.register("greet", my_tool, "A greeting tool", {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Name to greet"}},
        "required": ["name"],
    })

    schemas = r.get_schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "greet"
    assert s["function"]["description"] == "A greeting tool"
    assert s["function"]["parameters"]["required"] == ["name"]


@pytest.mark.asyncio
async def test_execute_success():
    r = make_registry()

    async def async_tool(name: str) -> str:
        return json.dumps({"result": f"hello {name}", "success": True})

    r.register("greet", async_tool, "", {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    })

    result = await r.execute("greet", {"name": "Xens"})
    parsed = json.loads(result) if isinstance(result, str) else result
    assert parsed["success"] is True
    assert parsed["result"] == "hello Xens"


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    r = make_registry()
    result = await r.execute("nonexistent", {})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "not found" in parsed["error"]


@pytest.mark.asyncio
async def test_execute_missing_required_param():
    r = make_registry()

    def sync_tool(name: str) -> str:
        return json.dumps({"success": True})

    r.register("greet", sync_tool, "", {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    })

    result = await r.execute("greet", {})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "Missing required" in parsed["error"]


@pytest.mark.asyncio
async def test_execute_invalid_type():
    r = make_registry()

    def sync_tool(count: int) -> str:
        return json.dumps({"success": True, "count": count})

    r.register("count", sync_tool, "", {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    })

    result = await r.execute("count", {"count": "not_a_number"})
    parsed = json.loads(result)
    assert parsed["success"] is False


@pytest.mark.asyncio
async def test_execute_enum_validation():
    r = make_registry()

    def sync_tool(mode: str) -> str:
        return json.dumps({"success": True})

    r.register("set_mode", sync_tool, "", {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["on", "off"]}},
        "required": ["mode"],
    })

    result = await r.execute("set_mode", {"mode": "invalid"})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "must be one of" in parsed["error"]


def test_tier_gating():
    r = make_registry()

    def free_tool():
        return "free"

    def pro_tool():
        return "pro"

    r.register("free_tool", free_tool, "", tier="free")
    r.register("pro_tool", pro_tool, "", tier="pro")

    assert r.count == 1  # only free visible
    assert r.count_hidden == 1
    assert "free_tool" in r.tool_names
    assert "pro_tool" not in r.tool_names

    r.set_tier("pro")
    assert r.count == 2
    assert "pro_tool" in r.tool_names


@pytest.mark.asyncio
async def test_execute_tier_blocked():
    r = make_registry()

    def pro_tool():
        return json.dumps({"success": True})

    r.register("pro_tool", pro_tool, "", tier="pro")

    result = await r.execute("pro_tool", {})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "requires pro tier" in parsed["error"]


def test_tool_names_property():
    r = make_registry()

    def a():
        return "a"

    def b():
        return "b"

    r.register("tool_a", a, "", tier="free")
    r.register("tool_b", b, "", tier="free")

    names = r.tool_names
    assert len(names) == 2
    assert "tool_a" in names
    assert "tool_b" in names


def test_internal_tool_hidden_from_schemas():
    r = make_registry()

    def public_tool():
        return "ok"

    def internal_tool():
        return "internal"

    r.register("public_tool", public_tool, "public", tier="free")
    r.register("internal_tool", internal_tool, "internal", tier="free", internal=True)

    schemas = r.get_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "public_tool" in names
    assert "internal_tool" not in names
    assert "internal_tool" in r._tools

    # internal tools never appear in tool_names
    assert "internal_tool" not in r.tool_names


def test_internal_tool_still_executable():
    r = make_registry()

    def inner():
        return json.dumps({"success": True, "from": "internal"})

    r.register("inner", inner, "", tier="free", internal=True)

    # Should still be callable via execute for system use
    import asyncio
    result = asyncio.run(r.execute("inner", {}))
    parsed = json.loads(result) if isinstance(result, str) else result
    assert parsed["success"] is True
    assert parsed["from"] == "internal"


def test_get_schemas_by_names():
    r = make_registry()

    def a():
        return "a"

    def b():
        return "b"

    r.register("tool_a", a, "desc a", {"type": "object", "properties": {}})
    r.register("tool_b", b, "desc b", {"type": "object", "properties": {}})

    schemas = r.get_schemas_by_names(["tool_a"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "tool_a"

    schemas = r.get_schemas_by_names(["tool_a", "nonexistent"])
    assert len(schemas) == 1

    schemas = r.get_schemas_by_names([])
    assert schemas == []



