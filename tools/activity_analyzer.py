import json
import os
import time
from collections import defaultdict, Counter
from datetime import datetime
from typing import Optional
from .registry import register

DATA_DIR = os.path.join(os.path.expanduser("~"), ".ainslup")
HABITS_FILE = os.path.join(DATA_DIR, "habits.json")


def _get_events(since: float, until: Optional[float] = None) -> list:
    path = os.path.join(DATA_DIR, "events.json")
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                all_events = json.load(f)
            result = [e for e in all_events if e.get("ts", 0) >= since]
            if until is not None:
                result = [e for e in result if e.get("ts", 0) < until]
            return result[-2000:]
    except Exception:
        pass
    return []


def _load_habits():
    try:
        if os.path.exists(HABITS_FILE):
            with open(HABITS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_habits(habits):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HABITS_FILE, "w") as f:
        json.dump(habits, f, indent=2)


def _describe_slot(hour: int) -> str:
    if hour < 6:
        return "early_morning"
    elif hour < 9:
        return "morning"
    elif hour < 12:
        return "late_morning"
    elif hour < 14:
        return "noon"
    elif hour < 17:
        return "afternoon"
    elif hour < 20:
        return "evening"
    elif hour < 23:
        return "night"
    return "late_night"


@register(
    name="detect_peak_hours",
    description="Detectar horas del dia con mayor actividad del usuario",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Dias a analizar"},
        },
        "required": [],
    },
    tier="premium",
)
def detect_peak_hours(days: int = 7) -> str:
    now = time.time()
    cutoff = now - (days * 86400)
    data = _get_events(cutoff)
    hourly = defaultdict(int)
    for e in data:
        ts = e.get("ts", 0)
        if ts >= cutoff:
            dt = datetime.fromtimestamp(ts)
            hourly[dt.hour] += 1
    if not hourly:
        return json.dumps({"success": True, "data": [], "message": "Sin datos suficientes"})
    total = sum(hourly.values())
    sorted_hours = sorted(hourly.items(), key=lambda x: -x[1])
    lines = [f"Horas activas (ultimos {days} dias, {total} eventos):"]
    for h, c in sorted_hours[:5]:
        lines.append(f"  {h:02d}:00 -> {c} eventos ({c/total*100:.0f}%)")
    return json.dumps({
        "success": True,
        "data": [{"hour": h, "count": c, "pct": round(c / total * 100, 1)} for h, c in sorted_hours[:5]],
        "message": "\n".join(lines),
    })


@register(
    name="detect_trends",
    description="Detectar tendencias de actividad reciente vs historica",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Dias a comparar"},
        },
        "required": [],
    },
    tier="premium",
)
def detect_trends(days: int = 3) -> str:
    now = time.time()
    recent = _get_events(now - 86400)
    older = _get_events(now - 86400 * days * 2, now - 86400 * days)
    ratio = len(recent) / max(len(older), 1)
    trend = "estable"
    if ratio > 1.5:
        trend = "en aumento"
    elif ratio < 0.5:
        trend = "en descenso"
    return json.dumps({
        "success": True,
        "data": {
            "trend": trend,
            "ratio": round(ratio, 2),
            "recent_count": len(recent),
            "older_count": len(older),
        },
    })


@register(
    name="detect_habits",
    description="Detectar patrones de comportamiento del usuario (horarios activos, apps frecuentes)",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Dias de historial a analizar"},
        },
        "required": [],
    },
    tier="premium",
)
def detect_habits(days: int = 14) -> str:
    now = time.time()
    cutoff = now - (days * 86400)
    events = _get_events(cutoff)
    if not events:
        return json.dumps({"success": True, "data": [], "message": "Sin datos suficientes para detectar patrones"})

    hourly = defaultdict(int)
    for e in events:
        ts = e.get("ts", 0)
        if ts:
            dt = datetime.fromtimestamp(ts)
            hourly[dt.hour] += 1

    habits = []
    max_count = max(hourly.values()) if hourly else 1
    for h, c in sorted(hourly.items()):
        pct = c / max_count
        if c >= 3 and pct >= 0.3:
            habits.append({
                "type": "active_hour",
                "hour": h,
                "slot": _describe_slot(h),
                "count": c,
                "confidence": round(min(pct, 1.0), 2),
            })

    _save_habits(habits)
    if not habits:
        return json.dumps({"success": True, "data": [], "message": "No se detectaron patrones significativos"})

    lines = [f"Patrones detectados ({len(habits)}):"]
    for h in sorted(habits, key=lambda x: -x["confidence"]):
        lines.append(f"  Activo a las {h['hour']:02d}:00 ({h['slot']}) - confianza {h['confidence']:.0%}")
    return json.dumps({"success": True, "data": habits, "message": "\n".join(lines)})


@register(
    name="get_habits",
    description="Obtener patrones de comportamiento detectados",
    parameters={
        "type": "object",
        "properties": {
            "min_confidence": {"type": "number", "description": "Confianza minima (0-1)"},
        },
        "required": [],
    },
    tier="premium",
)
def get_habits(min_confidence: float = 0.3) -> str:
    habits = _load_habits()
    filtered = [h for h in habits if h.get("confidence", 0) >= min_confidence]
    if not filtered:
        return json.dumps({"success": True, "data": [], "message": "No hay patrones con suficiente confianza"})
    lines = ["Tus patrones de comportamiento:"]
    for h in sorted(filtered, key=lambda x: -x["confidence"]):
        lines.append(f"  Sueles estar activo a las {h['hour']:02d}:00 ({h['slot']}) - {h['confidence']:.0%} confianza")
    return json.dumps({"success": True, "data": filtered, "message": "\n".join(lines)})


@register(
    name="get_activity_summary",
    description="Obtener resumen completo de actividad: horas pico, tendencias y patrones de comportamiento",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Dias a analizar para horas pico y tendencias"},
        },
        "required": [],
    },
    tier="premium",
)
def get_activity_summary(days: int = 7) -> str:
    now = time.time()
    cutoff = now - (days * 86400)

    data = _get_events(cutoff)
    hourly = defaultdict(int)
    for e in data:
        ts = e.get("ts", 0)
        if ts >= cutoff:
            dt = datetime.fromtimestamp(ts)
            hourly[dt.hour] += 1

    peak_hours = []
    if hourly:
        total = sum(hourly.values())
        sorted_hours = sorted(hourly.items(), key=lambda x: -x[1])
        peak_hours = [{"hour": h, "count": c, "pct": round(c / total * 100, 1)} for h, c in sorted_hours[:5]]

    recent = _get_events(now - 86400)
    older = _get_events(now - 86400 * days * 2, now - 86400 * days)
    ratio = len(recent) / max(len(older), 1)
    trend = "estable"
    if ratio > 1.5:
        trend = "en aumento"
    elif ratio < 0.5:
        trend = "en descenso"
    trends_data = {
        "trend": trend,
        "ratio": round(ratio, 2),
        "recent_count": len(recent),
        "older_count": len(older),
    }

    habits = _load_habits()

    return json.dumps({
        "success": True,
        "data": {
            "peak_hours": peak_hours,
            "trends": trends_data,
            "habits": habits,
        },
    })
