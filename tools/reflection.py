import json
import os
import time
from datetime import datetime
from .registry import register

DATA_DIR = os.path.join(os.path.expanduser("~"), ".ainslup")
REFLECTIONS_FILE = os.path.join(DATA_DIR, "reflections.json")


def _load():
    try:
        if os.path.exists(REFLECTIONS_FILE):
            with open(REFLECTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REFLECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@register(
    name="reflect",
    description="Reflexionar sobre una accion o resultado. Sirve para que el agente aprenda de sus errores.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Tema de la reflexion"},
            "observation": {"type": "string", "description": "Que ocurrio?"},
            "lesson": {"type": "string", "description": "Que se aprendio?"},
            "action_plan": {"type": "string", "description": "Que hacer diferente la proxima vez?"},
        },
        "required": ["topic", "observation"],
    },
    tier="premium",
)
def reflect(topic: str, observation: str, lesson: str = "", action_plan: str = "") -> str:
    entry = {
        "topic": topic,
        "observation": observation,
        "lesson": lesson,
        "action_plan": action_plan,
        "timestamp": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data = _load()
    data.append(entry)
    if len(data) > 200:
        data = data[-200:]
    _save(data)
    return f"Reflexion guardada sobre '{topic}'"


@register(
    name="list_reflections",
    description="Listar reflexiones guardadas",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Filtrar por tema (opcional)"},
            "limit": {"type": "integer", "description": "Maximo de resultados"},
        },
        "required": [],
    },
    tier="premium",
)
def list_reflections(topic: str = "", limit: int = 10) -> str:
    data = _load()
    if topic:
        data = [d for d in data if topic.lower() in d.get("topic", "").lower()]
    if not data:
        return "No hay reflexiones guardadas"
    data = data[-limit:]
    lines = [f"Reflexiones ({len(data)}):"]
    for d in data:
        lines.append(f"  [{d.get('date','?')}] {d.get('topic','?')}: {d.get('observation','')[:80]}")
        if d.get("lesson"):
            lines.append(f"    Leccion: {d['lesson'][:80]}")
    return "\n".join(lines)


@register(
    name="get_context_from_reflections",
    description="Obtener contexto de reflexiones relevantes para un tema",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Tema a buscar"},
        },
        "required": ["topic"],
    },
    tier="premium",
)
def get_context_from_reflections(topic: str) -> str:
    data = _load()
    relevant = [d for d in data if topic.lower() in d.get("topic", "").lower()]
    if not relevant:
        return ""
    lines = ["Reflexiones relevantes:"]
    for d in relevant[-3:]:
        lines.append(f"- {d.get('observation','')[:100]}")
        if d.get("lesson"):
            lines.append(f"  -> {d.get('lesson','')[:100]}")
    return "\n".join(lines)
