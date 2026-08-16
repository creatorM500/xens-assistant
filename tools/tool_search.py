import json
from .registry import register, registry

_discovered_tools: set[str] = set()

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

    _discovered_tools.update(to_discover)
    schemas = registry.get_schemas_by_names(list(to_discover))
    added = len(to_discover)
    visible = len(registry.tool_names) + len(_discovered_tools)
    names_list = ", ".join(sorted(to_discover))
    return f"Discovered {added} tool(s): {names_list}. Now available: {visible} tools."
