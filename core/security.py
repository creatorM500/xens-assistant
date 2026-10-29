"""Security controls for local tool execution."""
import json
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from .paths import DATA_HOME

_CONFIG = DATA_HOME / "permissions.json"
_AUDIT = DATA_HOME / "logs" / "audit.jsonl"
_confirmation_handler = ContextVar("ainslup_confirmation_handler", default=None)

DEFAULTS = {"safe": "allow", "confirm": "ask", "dangerous": "deny"}
TOOL_RISKS = {
    "send_email": "confirm", "write_file": "confirm", "run_command": "dangerous",
    "execute_code": "dangerous", "delete_email_credentials": "confirm",
    "delete_rule": "confirm", "delete_event": "confirm", "delete_trigger": "confirm",
    "macro_delete": "confirm", "email_finish_gmail": "confirm",
}
COMMAND_BLOCKLIST = re.compile(
    r"(^|[&|;])\s*(del|erase|format|shutdown|reboot|diskpart)\b|"
    r"\b(rm\s+-rf|\breg\s+delete\b|drop\s+database|truncate\s+table)\b",
    re.I,
)


def _load():
    try:
        data = json.loads(_CONFIG.read_text(encoding="utf-8"))
        return {"safe_mode": bool(data.get("safe_mode", False)),
                "permissions": dict(data.get("permissions", {}))}
    except Exception:
        return {"safe_mode": False, "permissions": {}}


def settings():
    return _load()


def set_settings(safe_mode=None, permissions=None):
    data = _load()
    if safe_mode is not None:
        data["safe_mode"] = bool(safe_mode)
    if permissions is not None:
        data["permissions"] = dict(permissions)
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def risk_for(name):
    return TOOL_RISKS.get(name, "safe")


def set_confirmation_handler(handler):
    return _confirmation_handler.set(handler)


def reset_confirmation_handler(token):
    _confirmation_handler.reset(token)


def audit(tool, args, decision, risk, detail=""):
    record = {"time": datetime.now(timezone.utc).isoformat(), "tool": tool,
              "args": args, "decision": decision, "risk": risk}
    if detail:
        record["detail"] = detail
    try:
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def blocked_command(args):
    command = str((args or {}).get("command", ""))
    return bool(command and COMMAND_BLOCKLIST.search(command))


async def authorize(tool, args, risk):
    if blocked_command(args):
        audit(tool, args, "blocked", "dangerous", "command denylist")
        return False, "Comando bloqueado por seguridad"
    cfg = _load()
    permission = cfg["permissions"].get(tool, DEFAULTS.get(risk, "ask"))
    if cfg["safe_mode"]:
        audit(tool, args, "simulated", risk, "safe mode")
        return True, "SIMULATED"
    if permission == "deny" or (risk == "dangerous" and permission != "allow"):
        audit(tool, args, "denied", risk, "permission")
        return False, "Herramienta denegada por permisos"
    if permission == "ask":
        handler = _confirmation_handler.get()
        if handler is None:
            audit(tool, args, "denied", risk, "confirmation unavailable")
            return False, "Se requiere confirmación del usuario"
        approved = await handler(tool, args, risk)
        audit(tool, args, "allowed" if approved else "denied", risk, "user confirmation")
        return bool(approved), "" if approved else "Operación rechazada por el usuario"
    audit(tool, args, "allowed", risk)
    return True, ""
