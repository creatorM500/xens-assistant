"""Catálogo interno de modelos y capacidades.

Los aliases son estables para el usuario; los IDs son intercambiables por
precio, disponibilidad y rendimiento.
"""

MODEL_CATALOG = {
    "Flash": {
        "description": "Chat rápido y económico",
        "models": ["xiaomi/mimo-v2.6-flash", "deepseek/deepseek-v4.1-flash", "minimax/minimax-m3.1-flash"],
        "capabilities": ["text", "tools"],
    },
    "Core": {
        "description": "Asistente general equilibrado",
        "models": ["deepseek/deepseek-v4.1-flash", "xiaomi/mimo-v2.6-flash", "minimax/minimax-m3.1-flash"],
        "capabilities": ["text", "tools", "long_context"],
    },
    "Think": {
        "description": "Razonamiento y problemas complejos",
        "models": ["xiaomi/mimo-v2.6-flash", "deepseek/deepseek-r1", "minimax/minimax-m3.1-flash"],
        "capabilities": ["text", "reasoning", "tools"],
    },
    "Code": {
        "description": "Programación y reparación de proyectos",
        "models": ["qwen/qwen-2.5-coder-32b-instruct", "xiaomi/mimo-v2.6-flash", "minimax/minimax-m3.1-flash"],
        "capabilities": ["text", "code", "tools"],
    },
    "Research": {
        "description": "Investigación y síntesis de contexto largo",
        "models": ["deepseek/deepseek-v4.1-flash", "xiaomi/mimo-v2.6-flash", "minimax/minimax-m3.1-flash"],
        "capabilities": ["text", "long_context", "tools"],
    },
    "Vision": {
        "description": "Pantalla, imágenes y contenido visual",
        "models": ["google/gemini-2.0-flash-001", "xiaomi/mimo-v2.6-flash"],
        "capabilities": ["text", "vision"],
    },
    "Ultra": {
        "description": "Tareas exigentes y análisis profundo",
        "models": ["minimax/minimax-m3.1-flash", "deepseek/deepseek-v4-pro", "anthropic/claude-sonnet-4"],
        "capabilities": ["text", "reasoning", "code", "tools", "long_context"],
    },
}


def catalog_for(alias=None):
    if alias:
        return MODEL_CATALOG.get(alias, {})
    return MODEL_CATALOG


def fallback_models(alias):
    return list(MODEL_CATALOG.get(alias, {}).get("models", []))
