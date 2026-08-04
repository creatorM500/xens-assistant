from .registry import register

_RISK_PROFILES = {
    "read_file":       {"risk": 0.1},
    "write_file":      {"risk": 0.5},
    "execute_code":    {"risk": 0.7},
    "web_search":      {"risk": 0.2},
    "browser_navigate": {"risk": 0.3},
    "win32_click":     {"risk": 0.6},
    "win32_key_press": {"risk": 0.6},
    "win32_window_close": {"risk": 0.8},
    "send_email":      {"risk": 0.3},
    "whatsapp_send":   {"risk": 0.4},
    "speak":           {"risk": 0.1},
    "take_screenshot": {"risk": 0.1},
}


@register(
    name="simulate_action",
    description="Simular una accion antes de ejecutarla para evaluar riesgo y confianza",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "Nombre de la accion a simular"},
            "args_text": {"type": "string", "description": "Argumentos como texto para analizar riesgo"},
        },
        "required": ["action"],
    },
    tier="premium",
)
def simulate_action(action: str, args_text: str = "") -> str:
    profile = _RISK_PROFILES.get(action, {"risk": 0.5})
    base_risk = profile["risk"]
    risk_mod = 0.0
    args_lower = args_text.lower()
    if any(kw in args_lower for kw in ("delete", "rm ", "drop", "format", "sudo", "admin")):
        risk_mod += 0.3
    if any(kw in args_lower for kw in ("backup", "copy", "read-only", "view")):
        risk_mod -= 0.2
    total_risk = max(0.0, min(1.0, base_risk + risk_mod))
    confidence = max(0.0, 1.0 - total_risk)
    recommendation = "proceed" if confidence >= 0.5 else "caution" if confidence >= 0.3 else "block"
    return (
        f"Simulacion para '{action}':\n"
        f"  Riesgo base: {base_risk:.1f}\n"
        f"  Modificador: {risk_mod:+.1f}\n"
        f"  Riesgo total: {total_risk:.1f}\n"
        f"  Confianza: {confidence:.2f}\n"
        f"  Recomendacion: {recommendation}"
    )


@register(
    name="compare_actions",
    description="Comparar multiples acciones simuladas y ordenarlas por confianza",
    parameters={
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de nombres de acciones a comparar",
            },
        },
        "required": ["actions"],
    },
    tier="premium",
)
def compare_actions(actions: list) -> str:
    results = []
    for action in actions:
        profile = _RISK_PROFILES.get(action, {"risk": 0.5})
        risk = profile["risk"]
        confidence = 1.0 - risk
        results.append((confidence, action, risk))
    results.sort(key=lambda x: -x[0])
    lines = ["Acciones ordenadas por confianza:"]
    for confidence, action, risk in results:
        lines.append(f"  {action}: confianza {confidence:.2f}, riesgo {risk:.1f}")
    return "\n".join(lines)
