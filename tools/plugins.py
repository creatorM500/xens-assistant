import glob
import importlib.util
import json
import os
import sys
from typing import Callable, Optional
from .registry import register

_PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..", "plugins")
_USER_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".ainslup", "plugins")
_plugin_cache = []


def _discover():
    global _plugin_cache
    _plugin_cache = []
    loaded = []
    os.makedirs(_PLUGIN_DIR, exist_ok=True)
    init_file = os.path.join(_PLUGIN_DIR, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            f.write("# plugins\n")
    sys.path.insert(0, os.path.dirname(_PLUGIN_DIR))
    try:
        for pyfile in sorted(glob.glob(os.path.join(_PLUGIN_DIR, "*.py"))):
            basename = os.path.basename(pyfile)
            if basename == "__init__.py":
                continue
            modname = f"plugins.{basename[:-3]}"
            if modname in sys.modules:
                continue
            try:
                spec = importlib.util.spec_from_file_location(modname, pyfile)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "register_plugin"):
                        result = mod.register_plugin()
                        if result:
                            for name, fn, schema in result:
                                _plugin_cache.append((name, fn, schema))
                    loaded.append(basename[:-3])
            except Exception:
                pass
    finally:
        sys.path = sys.path[1:]

    os.makedirs(_USER_PLUGIN_DIR, exist_ok=True)
    for entry in sorted(os.listdir(_USER_PLUGIN_DIR)):
        plugin_path = os.path.join(_USER_PLUGIN_DIR, entry)
        json_path = os.path.join(plugin_path, "plugin.json")
        init_path = os.path.join(plugin_path, "__init__.py")
        if not os.path.isfile(json_path) or not os.path.isfile(init_path):
            continue
        modname = f"user_plugins.{entry}"
        if modname in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(modname, init_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "register_plugin"):
                    result = mod.register_plugin()
                    if result:
                        for name, fn, schema in result:
                            _plugin_cache.append((name, fn, schema))
                loaded.append(entry)
        except Exception:
            pass
    _register_plugin_tools()
    return loaded


def _register_plugin_tools():
    """Registra las herramientas de los plugins en el registry para que sean ejecutables."""
    from .registry import registry
    for name, fn, schema in _plugin_cache:
        if name in registry.tool_names:
            continue
        func = (schema or {}).get("function", {}) if isinstance(schema, dict) else {}
        registry.register(
            name, fn,
            description=func.get("description") or f"Plugin tool: {name}",
            parameters=func.get("parameters") or {"type": "object", "properties": {}},
            tier="free",
            timeout=120,
        )


@register(
    name="plugins_discover",
    description="Descubrir y cargar plugins desde plugins/ y ~/.ainslup/plugins/",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def plugins_discover() -> str:
    loaded = _discover()
    if loaded:
        return f"Plugins cargados: {', '.join(loaded)}"
    return "No se encontraron plugins"


@register(
    name="plugins_list",
    description="Listar plugins cargados y sus herramientas",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def plugins_list() -> str:
    if not _plugin_cache:
        return "No hay plugins cargados"
    lines = ["Plugins activos:"]
    seen = set()
    for name, fn, schema in _plugin_cache:
        desc = schema.get("function", {}).get("description", "")[:60] if schema else ""
        if name not in seen:
            seen.add(name)
            lines.append(f"  {name}: {desc}")
    return "\n".join(lines)


def get_plugin_tools() -> list:
    schemas = []
    dispatch = {}
    for name, fn, schema in _plugin_cache:
        schemas.append(schema)
        dispatch[name] = fn
    return schemas, dispatch
