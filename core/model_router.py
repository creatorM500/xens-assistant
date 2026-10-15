import logging
from typing import Optional

from .tier_config import tier_config

logger = logging.getLogger("xens.router")

# Roles de costo por modelo. El router elige el orden barato -> capaz según
# la clase de tarea, para que una tarea sencilla nunca pague un modelo caro.
MODEL_ROLES = {
    "mistral-nemo": "cheap",
    "mistralai/mistral-nemo": "cheap",
    "qwen-2.5-coder-32b-instruct": "specialized",
    "qwen/qwen-2.5-coder-32b-instruct": "specialized",
    "deepseek-chat": "cheap",
    "community/vendouple/deepseek-v3.2": "cheap",
    "deepseek-v3.2": "cheap",
    "nvidia/nemotron-3-ultra": "cheap",
    "nemotron-3-ultra": "cheap",
    "mistral-medium-latest": "medium",
    "mistral-medium": "medium",
    "mistral-small-2506": "medium",
    "mistral-small": "medium",
    "gpt-4o-mini": "specialized",
    "gemini-2.0-flash-001": "specialized",
    "google/gemini-2.0-flash-001": "specialized",
    "gpt-4o": "specialized",
    "deepseek-r1": "specialized",
    "deepseek/deepseek-r1": "specialized",
    "anthropic/claude-sonnet-4": "frontier",
    "claude-sonnet-4": "frontier",
}

# Preferencia de rol por clase de tarea (primero = el que se intenta primero).
ROLE_ORDER = {
    "chat": ["cheap", "medium", "specialized", "frontier"],
    "assistant": ["medium", "cheap", "specialized", "frontier"],
    "full_capacity": ["frontier", "specialized", "medium", "cheap"],
}

TASK_CLASSES = ("chat", "assistant", "full_capacity")


def _model_role(model: str) -> str:
    if not model:
        return "medium"
    name = model.strip().lower()
    if name in MODEL_ROLES:
        return MODEL_ROLES[name]
    tail = name.rsplit("/", 1)[-1]
    if tail in MODEL_ROLES:
        return MODEL_ROLES[tail]
    for key, role in MODEL_ROLES.items():
        if key in name:
            return role
    return "medium"


def classify_task(text: str, message_count: int = 0) -> str:
    """Clase de tarea: chat (simple), assistant (herramientas), full_capacity."""
    from ..tools.modes import _classify_message

    cls = _classify_message(text or "")
    if message_count >= 20 or len(text or "") > 300:
        return "full_capacity"
    return cls


def pick(tier: str, text: str, message_count: int = 0, escalate: int = 0) -> list[dict]:
    """Devuelve la lista ordenada de entradas {provider, model} del tier para
    la tarea (barato -> capaz), con fallback automático al siguiente disponible.

    escalate > 0 sube la clase de tarea (tras errores consecutivos).
    """
    cls = classify_task(text, message_count)
    if escalate >= 2:
        cls = "full_capacity"
    elif escalate == 1 and cls == "chat":
        cls = "assistant"

    entries = tier_config.get_models(tier_config.models_tier(tier))
    order = ROLE_ORDER.get(cls, ROLE_ORDER["assistant"])

    def rank(entry) -> int:
        role = _model_role(entry.get("model", ""))
        try:
            return order.index(role)
        except ValueError:
            return len(order)  # roles no contemplados van al final

    seen: set[str] = set()
    ranked: list[dict] = []
    for entry in sorted(entries, key=rank):
        key = f"{entry.get('provider')}:{entry.get('model')}"
        if key in seen:
            continue
        seen.add(key)
        ranked.append(entry)
    return ranked or entries