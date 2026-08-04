import json
import os
import time
from datetime import datetime
from .registry import register

DATA_DIR = os.path.join(os.path.expanduser("~"), ".xens")
ANALYTICS_FILE = os.path.join(DATA_DIR, "analytics.json")


def _load():
    try:
        if os.path.exists(ANALYTICS_FILE):
            with open(ANALYTICS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"tool_calls": {}, "costs": [], "sessions": [], "errors": []}


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@register(
    name="track_tool_call",
    description="Registrar una llamada a herramienta para analytics",
    parameters={
        "type": "object",
        "properties": {
            "tool": {"type": "string", "description": "Nombre de la herramienta"},
            "success": {"type": "boolean", "description": "Si fue exitosa"},
            "duration_ms": {"type": "number", "description": "Duracion en ms"},
            "tokens_used": {"type": "integer", "description": "Tokens usados (opcional)"},
        },
        "required": ["tool", "success", "duration_ms"],
    },
    tier="free",
)
def track_tool_call(tool: str, success: bool, duration_ms: float, tokens_used: int = 0) -> str:
    data = _load()
    if tool not in data["tool_calls"]:
        data["tool_calls"][tool] = {"calls": 0, "success": 0, "fail": 0, "total_ms": 0}
    data["tool_calls"][tool]["calls"] += 1
    data["tool_calls"][tool]["success"] += 1 if success else 0
    data["tool_calls"][tool]["fail"] += 0 if success else 1
    data["tool_calls"][tool]["total_ms"] += duration_ms
    _save(data)
    return f"Tracked {tool}: {'ok' if success else 'fail'} ({duration_ms}ms)"


@register(
    name="get_analytics_summary",
    description="Obtener resumen de analytics: herramientas mas usadas, tasa de exito, costos",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="free",
)
def get_analytics_summary() -> str:
    data = _load()
    if not data["tool_calls"]:
        return "No hay datos de analytics aun"
    lines = ["=== Resumen de Analytics ==="]
    total = sum(t["calls"] for t in data["tool_calls"].values())
    lines.append(f"Total llamadas: {total}")
    top = sorted(data["tool_calls"].items(), key=lambda x: -x[1]["calls"])[:5]
    for tool, stats in top:
        rate = stats["success"] / max(stats["calls"], 1) * 100
        avg = stats["total_ms"] / max(stats["calls"], 1)
        lines.append(f"  {tool}: {stats['calls']} llamadas, exito {rate:.0f}%, promedio {avg:.0f}ms")
    return "\n".join(lines)


@register(
    name="get_daily_stats",
    description="Obtener estadisticas de uso del dia de hoy",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="free",
)
def get_daily_stats() -> str:
    data = _load()
    today = datetime.now().strftime("%Y-%m-%d")
    session_today = [s for s in data.get("sessions", []) if s.get("date") == today]
    if not session_today:
        return f"Hoy ({today}): sin actividad registrada"
    total_queries = sum(s.get("queries", 0) for s in session_today)
    total_tokens = sum(s.get("tokens", 0) for s in session_today)
    return f"Hoy ({today}): {len(session_today)} sesiones, {total_queries} consultas, {total_tokens} tokens"
