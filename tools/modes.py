from .registry import register
"""
modes.py — Mode system: state machine with permissions, auto-classification, and hooks.
Ported from Omni modes.py with cleanup and JSON returns.
"""
import json, logging, re, time
from pathlib import Path
from datetime import datetime
from .event_bus import EventBus

logger = logging.getLogger("xens.tools.modes")

_DATA_DIR = Path.home() / ".xens"
_MODO_PATH = _DATA_DIR / "mode.json"
_STATE_PATH = _DATA_DIR / "state.json"

_MODES_BASE = {
    "chat": {
        "name": "Chat",
        "description": "Conversation only, no tools",
        "tools": False,
        "proactive": False,
        "auto_learn": False,
        "reflection": False,
        "permissions": {
            "execute_code": False, "read_files": False, "write_files": False,
            "web": False, "system": False, "clipboard": False,
        },
    },
    "assistant": {
        "name": "Assistant",
        "description": "Assistant with tools on demand",
        "tools": True,
        "proactive": False,
        "auto_learn": True,
        "reflection": True,
        "permissions": {
            "execute_code": True, "read_files": True, "write_files": True,
            "web": True, "system": True, "clipboard": True,
        },
    },
    "full_capacity": {
        "name": "Full Capacity",
        "description": "Maximum power: tools + proactive + monitoring",
        "tools": True,
        "proactive": True,
        "auto_learn": True,
        "reflection": True,
        "permissions": {
            "execute_code": True, "read_files": True, "write_files": True,
            "web": True, "system": True, "clipboard": True,
        },
    },
}

_MODES = {**_MODES_BASE, "auto": {
    "name": "Auto",
    "description": "Classifies each message into chat/assistant/full_capacity automatically",
    "tools": None, "proactive": None, "auto_learn": None, "reflection": None, "permissions": None,
}}

_current_mode = "auto"
_mode_hooks = []

# ── Auto classifier patterns ────────────────────────────────────
_PATTERN_TOOL = re.compile(
    r"\b(clima|hora|fecha|busca|buscar|internet|google|youtube|reddit|"
    r"traduce|traducir|calcula|calcular|cuanto es|resume|resumir|"
    r"abre|abrir|lee|leer|archivo|directorio|nota|recordatorio|"
    r"ejecuta|ejecutar|codigo|python|ventana|activa|aplicaciones|"
    r"portapapeles|inactivo|sistema|cpu|ram|sabes de mi|"
    r"lista|listar|guarda|crea|escribe|recuerda)\b", re.IGNORECASE,
)
_PATTERN_COMPLEX = re.compile(
    r"\b(analiza|compara|investiga|profundo|detallado|"
    r"y luego|y despues|primero|despues|paso a paso|"
    r"monitorea|vigila|observa|cada|periodicamente)\b", re.IGNORECASE,
)
_PATTERN_CHAT = re.compile(
    r"^(hola|buenas|buen(a|os) (dias|tardes|noches)|que tal|"
    r"como estas|ok|vale|gracias|si|no|jaja|claro|entiendo|"
    r"bien|perfecto|genial|excelente|dale|vamos|sale|de nada|adios|"
    r"chao|nos vemos|hasta luego|bye|saludos)\b.*$", re.IGNORECASE,
)
_CHAT_WORDS = {"hola", "buenas", "gracias", "ok", "vale", "si", "no",
               "jaja", "claro", "entiendo", "bien", "perfecto", "genial",
               "dale", "sale", "adios", "chao", "bye", "saludos"}


def _classify_message(text: str) -> str:
    t = text.strip()
    if not t:
        return "chat"
    words = set(t.lower().split())
    if _PATTERN_COMPLEX.search(t):
        return "full_capacity"
    if _PATTERN_TOOL.search(t):
        return "assistant"
    if _PATTERN_CHAT.match(t):
        return "chat"
    if len(t.split()) <= 3 and words.issubset(_CHAT_WORDS):
        return "chat"
    if len(t) > 100:
        return "full_capacity"
    if t.endswith("?") and len(t) < 30:
        return "assistant"
    return "assistant"


def _load_mode() -> str:
    global _current_mode
    try:
        if _MODO_PATH.exists():
            _current_mode = json.loads(_MODO_PATH.read_text(encoding="utf-8")).get("mode", "auto")
    except Exception:
        pass
    return _current_mode


def _save_mode(mode: str):
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _MODO_PATH.write_text(json.dumps({"mode": mode}), encoding="utf-8")
    except Exception:
        pass


@register(name="set_mode", description="Change the operation mode (chat/assistant/full_capacity/auto).", tier="free", internal=True)
def set_mode(mode: str) -> str:
    global _current_mode
    if mode not in _MODES:
        return json.dumps({"error": f"Invalid mode. Available: {', '.join(_MODES.keys())}", "success": False})
    old = _current_mode
    _current_mode = mode
    _save_mode(mode)
    EventBus.get_bus().emit("mode.changed", {"old": old, "new": mode})
    for hook in _mode_hooks:
        try:
            hook(old, mode)
        except Exception:
            pass
    cfg = _MODES[mode]
    return json.dumps({"success": True, "mode": mode, "name": cfg["name"], "description": cfg["description"]})


@register(name="get_mode", description="Get the current operation mode.", tier="free", internal=True)
def get_mode() -> str:
    return _current_mode


def get_config(text: str = "") -> dict:
    mode = _current_mode
    if mode == "auto" and text:
        mode = _classify_message(text)
    return _MODES_BASE.get(mode, _MODES_BASE["assistant"])


def get_permissions(text: str = "") -> dict:
    cfg = get_config(text)
    return cfg.get("permissions", {})


def check_permission(perm: str, text: str = "") -> bool:
    perms = get_permissions(text)
    return perms.get(perm, False)




def on_mode_change(hook):
    _mode_hooks.append(hook)
    return hook


# ── System state persistence ─────────────────────────────────────

_state = {
    "mode": "auto",
    "permissions_by_mode": {m: _MODES_BASE[m].get("permissions", {}) for m in _MODES_BASE},
    "recent_actions": [],
    "recent_errors": [],
    "proactive": {"enabled": False, "last_interaction": None, "suggestions_today": 0},
    "stats": {"total_actions": 0, "total_errors": 0},
}


def _load_state():
    global _state
    try:
        if _STATE_PATH.exists():
            _state.update(json.loads(_STATE_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass


def _save_state():
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(_state, indent=2), encoding="utf-8")
    except Exception:
        pass


@register(name="get_state", description="Get system state (actions, errors, proactive status).", tier="free", internal=True)
def get_state() -> str:
    return json.dumps({"success": True, **_state})


def log_action(action: str):
    _state["stats"]["total_actions"] += 1
    _state["recent_actions"].append({"action": action, "time": datetime.now().isoformat()})
    if len(_state["recent_actions"]) > 50:
        _state["recent_actions"] = _state["recent_actions"][-50:]
    _save_state()


def log_error(error: str):
    _state["stats"]["total_errors"] += 1
    _state["recent_errors"].append({"error": error, "time": datetime.now().isoformat()})
    if len(_state["recent_errors"]) > 20:
        _state["recent_errors"] = _state["recent_errors"][-20:]
    _save_state()


def update_proactive(enabled: bool = None):
    p = _state["proactive"]
    if enabled is not None:
        p["enabled"] = enabled
    p["last_interaction"] = datetime.now().isoformat()
    _save_state()


_load_mode()
_load_state()
