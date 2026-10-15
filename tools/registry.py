import json, time, logging, asyncio
from functools import wraps
from pathlib import Path

logger = logging.getLogger("xens.tools")

class ToolError(Exception):
    def __init__(self, message, code="TOOL_ERROR", details=None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

_TIER_MAP_PATH = Path(__file__).parent / "tier_map.json"


def _load_tier_map() -> dict:
    try:
        if _TIER_MAP_PATH.exists():
            return json.loads(_TIER_MAP_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load tier map: {e}")
    return {}


def _save_tier_map(tier_map: dict):
    try:
        _TIER_MAP_PATH.write_text(json.dumps(tier_map, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save tier map: {e}")


TIERS = {"free", "lite", "pro", "premium"}
DEFAULT_TIER = "free"


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._current_tier = "free"
        self._tier_map = _load_tier_map()

    def register(self, name, handler, description, parameters=None,
                 timeout=60, retry_on_error=False, tier="free", internal=False):
        if name in self._tools:
            logger.warning(f"Tool '{name}' already registered, overwriting")
        effective_tier = self._tier_map.get(name, tier)
        self._tools[name] = {
            "handler": handler,
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}},
            "timeout": timeout,
            "retry_on_error": retry_on_error,
            "tier": effective_tier,
            "internal": internal,
        }
        self._tier_map[name] = effective_tier

    def get_schemas(self, include_internal=False):
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            }
            for name, tool in self._tools.items()
            if self._is_available(name) and (include_internal or not tool.get("internal"))
        ]

    def get_schemas_by_names(self, names):
        result = []
        for name in names:
            tool = self._tools.get(name)
            if tool:
                result.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    }
                })
        return result

    def _is_available(self, name: str) -> bool:
        tool = self._tools.get(name)
        if not tool:
            return False
        if tool.get("internal"):
            return False
        required_tier = tool.get("tier", "free")
        return _tier_gte(self._current_tier, required_tier)

    def set_tier(self, tier: str):
        if tier not in TIERS:
            raise ValueError(f"Invalid tier '{tier}'. Must be one of: {', '.join(sorted(TIERS))}")
        self._current_tier = tier
        info_names = self.tool_names
        hidden = self.count_hidden
        logger.info(f"Tier set to '{tier}' — {len(info_names)} tools available ({hidden} hidden)")

    def get_tier(self) -> str:
        return self._current_tier

    def get_schemas(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            }
            for name, tool in self._tools.items() if self._is_available(name)
        ]

    async def execute(self, name, args):
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"error": f"Tool '{name}' not found", "success": False})
        if tool.get("internal"):
            pass  # internal tools bypass tier check, still executable by system
        elif not self._is_available(name):
            return json.dumps({"error": f"Tool '{name}' requires {tool['tier']} tier", "success": False, "required_tier": tool["tier"]})

        handler = tool["handler"]
        timeout = tool["timeout"]
        is_async = asyncio.iscoroutinefunction(handler)

        try:
            validated = self._validate_args(tool["parameters"], args)
        except ToolError as e:
            return json.dumps({"error": e.message, "code": e.code, "success": False})

        for attempt in range(2 if tool["retry_on_error"] else 1):
            try:
                if is_async:
                    result = await asyncio.wait_for(handler(**validated), timeout=timeout)
                else:
                    # Handler síncrono: ejecutarlo fuera del event loop con
                    # timeout real, para no congelar toda la app.
                    result = await asyncio.wait_for(
                        asyncio.to_thread(handler, **validated), timeout=timeout
                    )
                logger.debug(f"Tool '{name}' OK ({len(str(result))} chars)")
                return result
            except asyncio.TimeoutError:
                logger.warning(f"Tool '{name}' timed out ({timeout}s)")
                if attempt == 0 and tool["retry_on_error"]:
                    continue
                return json.dumps({"error": f"Tool '{name}' timed out after {timeout}s", "code": "TIMEOUT", "success": False})
            except ToolError as e:
                return json.dumps({"error": e.message, "code": e.code, "success": False})
            except Exception as e:
                logger.warning(f"Tool '{name}' failed: {e}")
                if attempt == 0 and tool["retry_on_error"]:
                    continue
                return json.dumps({"error": str(e), "code": "EXECUTION_ERROR", "success": False})

    def _validate_args(self, schema, args):
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be a JSON object", code="INVALID_TYPE")
        props = schema.get("properties", {})
        required = schema.get("required", [])
        validated = {}
        for key in required:
            if key not in args:
                raise ToolError(f"Missing required parameter: '{key}'", code="MISSING_PARAM")
        for key, value in args.items():
            if key not in props:
                continue
            prop = props[key]
            ptype = prop.get("type")
            if ptype == "string" and not isinstance(value, str):
                value = str(value)
            elif ptype == "integer" and not isinstance(value, int):
                try:
                    value = int(value)
                except:
                    raise ToolError(f"Parameter '{key}' must be an integer", code="INVALID_TYPE")
            elif ptype == "number" and not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except:
                    raise ToolError(f"Parameter '{key}' must be a number", code="INVALID_TYPE")
            elif ptype == "boolean":
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    low = value.strip().lower()
                    if low in ("true", "1", "yes", "si"):
                        value = True
                    elif low in ("false", "0", "no"):
                        value = False
                    else:
                        raise ToolError(f"Parameter '{key}' must be true or false", code="INVALID_TYPE")
                else:
                    value = bool(value)
            elif ptype == "array" and not isinstance(value, list):
                raise ToolError(f"Parameter '{key}' must be an array", code="INVALID_TYPE")
            elif ptype == "object" and not isinstance(value, dict):
                raise ToolError(f"Parameter '{key}' must be an object", code="INVALID_TYPE")
            if "enum" in prop and value not in prop["enum"]:
                raise ToolError(f"Parameter '{key}' must be one of: {', '.join(prop['enum'])}", code="INVALID_ENUM")
            validated[key] = value
        return validated

    @property
    def tool_names(self):
        return [name for name in self._tools if self._is_available(name)]

    @property
    def count(self):
        return len(self.tool_names)

    @property
    def count_hidden(self):
        return len(self._tools) - self.count

    @property
    def count_total(self):
        return len(self._tools)


def _tier_gte(current: str, required: str) -> bool:
    order = {"free": 0, "pro": 1, "premium": 2}
    return order.get(current, 0) >= order.get(required, 0)


registry = ToolRegistry()


def _schema_from_signature(fn) -> dict:
    """Build a JSON Schema from a function signature when no explicit parameters are given."""
    import inspect, typing
    sig = inspect.signature(fn)
    props: dict = {}
    required: list = []
    for name, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        ann = p.annotation
        origin = None
        try:
            origin = typing.get_origin(ann)
        except Exception:
            origin = None
        if origin is not None:
            args = typing.get_args(ann)
            if args and args[0] is not type(None):
                ann = args[0]
        ptype = "string"
        if ann is int:
            ptype = "integer"
        elif ann is bool:
            ptype = "boolean"
        elif ann is float:
            ptype = "number"
        elif ann in (list, tuple):
            ptype = "array"
        elif ann is dict:
            ptype = "object"
        if p.default is inspect.Parameter.empty:
            required.append(name)
        props[name] = {"type": ptype, "description": name}
    return {"type": "object", "properties": props, "required": required}


def register(name=None, description=None, parameters=None, timeout=None, retry_on_error=False, tier=None, internal=False):
    """Decorator that auto-registers a function as a tool when the module is imported."""
    def decorator(fn):
        _name = name or fn.__name__
        _desc = description or fn.__doc__ or ""
        params = parameters if parameters is not None else _schema_from_signature(fn)
        _params = params or {"type": "object", "properties": {}}
        _tier = tier or DEFAULT_TIER
        registry.register(_name, fn, _desc, _params, timeout or 60, retry_on_error or False, _tier, internal)
        return fn
    return decorator


_TOOL_MODULES = (
    "activity_analyzer", "analytics", "automations", "browser", "calendar", "code_exec",
    "computer", "desktop", "desktop_tray", "email", "event_bus", "files", "goals",
    "image_gen", "intent", "knowledge", "loop_guard", "media_downloader", "messaging", "modes",
    "monitoring", "music", "native_macros", "plugins", "proactive", "quick_input",
    "rag", "reflection", "reminders", "shell", "simulation_engine", "strategy",
    "sync_tier_config", "system", "tool_search", "uia", "user_profile", "vision",
    "voice", "voice_activation", "web", "working_memory",
)


def discover_tools():
    """Import all tool modules from tools/ directory to trigger @register decorators."""
    import importlib
    pkg = __name__.rsplit(".", 1)[0]
    count_before = registry.count_total
    modnames = None
    try:
        modnames = sorted(
            {
                f.stem
                for f in Path(__file__).parent.glob("*.py")
                if f.stem not in ("registry", "__init__") and not f.stem.startswith("_")
            }
        )
    except Exception:
        modnames = None
    if not modnames:
        modnames = list(_TOOL_MODULES)
    for modname in modnames:
        try:
            importlib.import_module(f"{pkg}.{modname}")
        except Exception as e:
            logger.warning(f"Failed to load tool module '{modname}': {e}")
    count_after = registry.count_total
    new = count_after - count_before
    if new > 0:
        logger.info(f"Auto-discovered {new} tool(s) ({count_after} total registered)")
    return new
