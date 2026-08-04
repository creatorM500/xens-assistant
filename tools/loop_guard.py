import time
import threading
from collections import defaultdict
from .registry import register

_MAX_CALLS_PER_MINUTE = 60
_WINDOW_SECONDS = 60

_call_history = defaultdict(list)
_lock = threading.Lock()
_paused = False


def _prune(window=_WINDOW_SECONDS):
    now = time.time()
    cutoff = now - window
    for tool in list(_call_history.keys()):
        _call_history[tool] = [t for t in _call_history[tool] if t > cutoff]
        if not _call_history[tool]:
            del _call_history[tool]


def check_rate_limit(tool: str) -> bool:
    with _lock:
        _prune()
        total = sum(len(v) for v in _call_history.values())
        if total >= _MAX_CALLS_PER_MINUTE:
            return False
        _call_history[tool].append(time.time())
        return True


@register(
    name="loop_guard_status",
    description="Estado del guardia anti-bucle: llamadas por minuto, herramientas activas",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="free",
)
def loop_guard_status() -> str:
    with _lock:
        _prune()
        total = sum(len(v) for v in _call_history.values())
        active = {k: len(v) for k, v in sorted(_call_history.items(), key=lambda x: -len(x[1]))[:5]}
    lines = [f"LoopGuard: {total}/{_MAX_CALLS_PER_MINUTE} llamadas en ultimo minuto"]
    if active:
        lines.append("Herramientas activas:")
        for t, c in active.items():
            lines.append(f"  {t}: {c} llamadas")
    if _paused:
        lines.append("Sistema PAUSADO")
    return "\n".join(lines)


@register(
    name="pause_agent",
    description="Pausar el agente para evitar loops",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="pro",
)
def pause_agent() -> str:
    global _paused
    _paused = True
    return "Agente pausado"


@register(
    name="resume_agent",
    description="Reanudar el agente tras una pausa",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    tier="pro",
)
def resume_agent() -> str:
    global _paused
    _paused = False
    return "Agente reanudado"


def is_paused() -> bool:
    return _paused
