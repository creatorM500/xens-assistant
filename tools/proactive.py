import time
import threading
from collections import deque
from typing import Optional
from .registry import register


class ProactiveEngine:
    def __init__(self):
        self._recent: deque = deque(maxlen=10)
        self._suggestions: deque = deque(maxlen=5)
        self._last_window = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="proactive")
        self._thread.start()

    def stop(self):
        self._running = False

    def observe_window(self, title: str):
        self._recent.append(("window", title, time.time()))
        if title and title != self._last_window:
            self._last_window = title
            self._generate_window_suggestion(title)

    def observe_clipboard(self, text: str):
        self._recent.append(("clipboard", text[:80], time.time()))
        self._generate_clipboard_suggestion(text)

    def _generate_window_suggestion(self, title: str):
        tl = title.lower()
        if "chrome" in tl or "edge" in tl or "firefox" in tl:
            self._suggestions.append({
                "type": "browser",
                "message": "Estas en el navegador. Necesitas buscar algo?",
                "context": {"window": title},
            })
        elif "spotify" in tl:
            self._suggestions.append({
                "type": "music",
                "message": "Quieres poner musica o buscar algo en Spotify?",
                "context": {"window": title},
            })
        elif "outlook" in tl or "mail" in tl:
            self._suggestions.append({
                "type": "email",
                "message": "Estas en el correo. Quieres que busque algun mensaje?",
                "context": {"window": title},
            })
        elif "code" in tl or "visual studio" in tl:
            self._suggestions.append({
                "type": "coding",
                "message": "Veo que estas programando. Necesitas ayuda con algo?",
                "context": {"window": title},
            })

    def _generate_clipboard_suggestion(self, text: str):
        if len(text) > 100:
            self._suggestions.append({
                "type": "long_text",
                "message": f"Copiaste {len(text)} caracteres. Quieres resumir, traducir o guardar?",
                "context": {"clipboard_length": len(text), "clipboard": text[:200]},
            })

    def pop_suggestion(self) -> Optional[dict]:
        if self._suggestions:
            return self._suggestions.popleft()
        return None

    def get_all_suggestions(self) -> list:
        return list(self._suggestions)

    def get_context(self) -> dict:
        ctx = {
            "last_window": self._last_window,
            "recent_events": [],
        }
        for etype, edata, ts in self._recent:
            age = time.time() - ts
            if age < 30:
                ctx["recent_events"].append({"type": etype, "data": edata, "seconds_ago": int(age)})
        return ctx

    def _loop(self):
        while self._running:
            time.sleep(1.0)


_engine: Optional[ProactiveEngine] = None


def get_engine() -> ProactiveEngine:
    global _engine
    if _engine is None:
        _engine = ProactiveEngine()
    return _engine


@register(
    name="start_proactive_engine",
    description="Iniciar el motor proactivo (sugerencias contextuales)",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def start_proactive_engine() -> str:
    eng = get_engine()
    eng.start()
    return "Motor proactivo iniciado"


@register(
    name="stop_proactive_engine",
    description="Detener el motor proactivo",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_proactive_engine() -> str:
    eng = get_engine()
    eng.stop()
    return "Motor proactivo detenido"


@register(
    name="get_suggestion",
    description="Obtener la siguiente sugerencia proactiva",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def get_suggestion() -> str:
    eng = get_engine()
    sug = eng.pop_suggestion()
    if sug:
        return f"Sugerencia: {sug['message']}"
    return "Sin sugerencias por ahora"
