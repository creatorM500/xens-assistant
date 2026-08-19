import json
from .registry import register, registry

# Tools descubiertas en esta sesión. Se mantienen en el contexto de la
# siguiente llamada LLM, por lo que están TOPEADAS con eviction LRU:
# descubrir más allá del límite evicta las menos usadas (ahorro de tokens).
_discovered_tools: set[str] = set()
_discovery_order: list[str] = []
_MAX_DISCOVERED = 40


def _touch(name: str):
    """Marca una tool como usada (LRU). Se llama al ejecutar una tool."""
    if name in _discovery_order:
        _discovery_order.remove(name)
        _discovery_order.append(name)


def _evict_oldest():
    while len(_discovered_tools) > _MAX_DISCOVERED and _discovery_order:
        oldest = _discovery_order.pop(0)
        _discovered_tools.discard(oldest)


def _discover(names) -> list[str]:
    """Agrega tools al set activo aplicando el límite LRU. Devuelve las
    evictadas (si las hay) para informarlo al modelo."""
    evicted = []
    for n in names:
        if n in _discovered_tools:
            _touch(n)
            continue
        _discovered_tools.add(n)
        _discovery_order.append(n)
        if len(_discovered_tools) > _MAX_DISCOVERED:
            oldest = _discovery_order.pop(0)
            _discovered_tools.discard(oldest)
            evicted.append(oldest)
    return evicted

_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    ("browser_", "browser"),
    ("win32_", "windows_ui"),
    ("uia_", "windows_uia"),
    ("spotify_", "spotify"),
    ("knowledge_", "knowledge_graph"),
    ("goal_", "goals"),
    ("macro_", "macros"),
    ("wm_", "working_memory"),
    ("rag_", "rag"),
    ("aprender_", "user_profile"),
    ("cognitive_", "cognition"),
    ("recall_", "memory"),
    ("learner_", "learning"),
    ("voice_activation_", "voice"),
    ("plugin_", "plugins"),
    ("mcp_", "mcp"),
    ("strategy_", "strategy"),
    ("simulate_", "simulation"),
    ("analytics_", "analytics"),
    ("loop_guard_", "system_guard"),
    ("reflect", "reflection"),
    ("list_reflections", "reflection"),
    ("get_context_from_reflections", "reflection"),
    ("email_", "email"),
    ("configure_", "setup"),
    ("delete_", "destructive"),
    ("start_", "monitoring"),
    ("stop_", "monitoring"),
    ("monitoring_", "monitoring"),
    ("observer_", "monitoring"),
    ("presence_", "monitoring"),
    ("notif", "monitoring"),
    ("quick_input", "utilities"),
    ("download_", "media"),
]

_CATEGORY_NAMES: dict[str, str] = {
    "browser": "Browser automation (Chrome CDP)",
    "windows_ui": "Windows mouse & keyboard simulation",
    "windows_uia": "Windows UI Automation (UIAccessibility)",
    "spotify": "Spotify music control",
    "knowledge_graph": "Knowledge graph (entities & relations)",
    "goals": "Goal tracking & progress management",
    "macros": "Keyboard/mouse macro playback",
    "working_memory": "Ephemeral key-value store (auto-expires)",
    "rag": "Semantic search & RAG query",
    "user_profile": "User learning & preference tracking",
    "cognition": "Cognitive facts with confidence decay",
    "memory": "Persistent recall storage",
    "learning": "Information extraction from messages",
    "voice": "Voice activation (wake word & conversation mode)",
    "plugins": "Plugin management",
    "mcp": "MCP (Model Context Protocol) server management",
    "strategy": "Strategic analysis & debate",
    "simulation": "Scenario simulation & A/B testing",
    "analytics": "Usage analytics & statistics",
    "system_guard": "Execution guard & safety limits",
    "reflection": "Agent self-reflection & learning from mistakes",
    "email": "Email (read, search, send)",
    "setup": "One-time configuration tools",
    "destructive": "Destructive operations (delete data)",
    "monitoring": "System monitoring (window, clipboard, presence, notifications)",
    "utilities": "Utility tools",
    "media": "Media downloading",
    "general": "General purpose tools",
}


def _infer_category(tool_name: str) -> str:
    for prefix, cat in _CATEGORY_PREFIXES:
        if tool_name.startswith(prefix):
            return cat
    return "general"


def get_available_tool_names() -> list[str]:
    return [n for n in registry.tool_names if n not in ("get_tool_schemas", "list_categories") and n not in _discovered_tools]


@register(
    name="list_categories",
    description="List all available tool categories with tool counts. Use this to discover what tools are available.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="free",
)
def list_categories() -> str:
    cats: dict[str, list[str]] = {}
    for name in get_available_tool_names():
        cat = _infer_category(name)
        cats.setdefault(cat, []).append(name)
    lines = ["Available tool categories:"]
    for cat_key in sorted(cats):
        tools = cats[cat_key]
        label = _CATEGORY_NAMES.get(cat_key, cat_key)
        lines.append(f"  {cat_key} ({len(tools)} tools): {label}")
        names = ", ".join(sorted(tools))
        lines.append(f"    {names}")
    return "\n".join(lines)


@register(
    name="get_tool_schemas",
    description="Get schemas for specific tools by name, category, or keyword. The system will make these available for use after discovery.",
    parameters={
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific tool names to discover (e.g. ['browser_navigate', 'spotify_play'])",
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Category names to discover all tools in (e.g. ['browser', 'spotify'])",
            },
            "query": {
                "type": "string",
                "description": "Keyword search across tool names and descriptions",
            },
        },
        "required": [],
    },
    tier="free",
)
def get_tool_schemas(names: list[str] = None, categories: list[str] = None, query: str = None) -> str:
    if isinstance(names, str):
        names = [names]
    if isinstance(categories, str):
        categories = [categories]
    if query is not None and not isinstance(query, str):
        query = str(query)
    available = set(get_available_tool_names())
    to_discover: set[str] = set()

    if names:
        for n in names:
            if n in available:
                to_discover.add(n)
            else:
                found = [t for t in available if n.lower() in t.lower()]
                to_discover.update(found)

    if categories:
        for cat in categories:
            cat_lower = cat.lower()
            for t in available:
                if _infer_category(t) == cat_lower or cat_lower in t.lower():
                    to_discover.add(t)

    if query:
        q = query.lower()
        for t in available:
            if q in t.lower():
                to_discover.add(t)

    if not to_discover:
        return "No tools matched the given criteria. Use list_categories to see available categories."

    evicted = _discover(list(to_discover))
    schemas = registry.get_schemas_by_names(list(to_discover))
    added = len(to_discover)
    visible = len(registry.tool_names) + len(_discovered_tools)
    names_list = ", ".join(sorted(to_discover))
    note = ""
    if evicted:
        note = (f" Note: {len(evicted)} least-used tool(s) were dropped from the "
                f"active set to save context: {', '.join(sorted(evicted))}. "
                f"Re-discover them if needed.")
    return f"Discovered {added} tool(s): {names_list}. Now available: {visible} tools.{note}"


@register(
    name="run_any_tool",
    description=(
        "Execute ANY tool by name with its arguments as a JSON string. "
        "Use this for tools you haven't discovered instead of get_tool_schemas — "
        "no need to wait a turn. The tool's tier still applies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact tool name (use list_categories to find it)"},
            "args_json": {"type": "string", "description": "Arguments as a JSON object string, e.g. '{\"url\": \"https://x.com\"}'. Use {} for tools without arguments."},
        },
        "required": ["name", "args_json"],
    },
    tier="free",
)
async def run_any_tool(name: str, args_json: str = "{}"):
    name = (name or "").strip()
    if not name or name not in registry._tools:
        return json.dumps({"error": f"Tool '{name}' not found. Use list_categories to see available tools.", "success": False})
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"args_json is not valid JSON: {e}. Fix the JSON and retry.", "success": False})
    if not isinstance(args, dict):
        return json.dumps({"error": "args_json must be a JSON object", "success": False})
    return await registry.execute(name, args)
