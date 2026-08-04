import threading
import time
from typing import Any, Optional
from .registry import register


class WorkingMemory:
    def __init__(self, default_ttl: float = 120.0):
        self._lock = threading.Lock()
        self._data: dict = {}
        self._default_ttl = default_ttl

    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        with self._lock:
            self._evict()
            self._data[key] = (value, time.time() + (ttl or self._default_ttl))

    def get(self, key: str) -> Any:
        with self._lock:
            self._evict()
            entry = self._data.get(key)
            if entry and time.time() < entry[1]:
                return entry[0]
            if entry:
                del self._data[key]
            return None

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)

    def snapshot(self) -> dict:
        with self._lock:
            self._evict()
            return {k: v[0] for k, v in self._data.items()}

    def clean(self, keep_keys: Optional[set] = None):
        with self._lock:
            self._evict()
            if keep_keys:
                to_keep = {k: v for k, v in self._data.items() if k in keep_keys}
                self._data.clear()
                self._data.update(to_keep)
            else:
                self._data.clear()

    def _evict(self):
        now = time.time()
        expired = [k for k, v in self._data.items() if now >= v[1]]
        for k in expired:
            del self._data[k]


working_memory = WorkingMemory()


@register(
    name="wm_set",
    description="Guardar un valor en memoria de trabajo (expira automaticamente)",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Clave"},
            "value": {"description": "Valor (cualquier tipo JSON)"},
            "ttl": {"type": "number", "description": "TTL en segundos (default 120)"},
        },
        "required": ["key", "value"],
    },
    tier="free",
    internal=True,
)
def wm_set(key: str, value: Any, ttl: Optional[float] = None) -> str:
    working_memory.set(key, value, ttl)
    return f"WM: {key} guardado"


@register(
    name="wm_get",
    description="Obtener un valor de la memoria de trabajo",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Clave a obtener"},
        },
        "required": ["key"],
    },
    tier="free",
    internal=True,
)
def wm_get(key: str) -> str:
    val = working_memory.get(key)
    if val is None:
        return f"WM: '{key}' no encontrado o expiro"
    return f"{key}: {val}"


@register(
    name="wm_snapshot",
    description="Ver toda la memoria de trabajo activa",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
    internal=True,
)
def wm_snapshot() -> str:
    snap = working_memory.snapshot()
    if not snap:
        return "Memoria de trabajo vacia"
    lines = ["Memoria de trabajo activa:"]
    for k, v in snap.items():
        lines.append(f"  {k}: {str(v)[:100]}")
    return "\n".join(lines)
