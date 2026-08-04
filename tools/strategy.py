import time
from dataclasses import dataclass, field
from typing import Any, Optional
from .registry import register


@dataclass
class Strategy:
    name: str
    description: str
    tools: list[str]
    confidence_threshold: float = 0.5


class StrategySelector:
    def __init__(self):
        self.strategies: dict[str, Strategy] = {}
        self.success_history: dict[str, list[float]] = {}
        self.failure_count: dict[str, int] = {}
        self.last_used: dict[str, float] = {}

    def register(self, strategy: Strategy):
        self.strategies[strategy.name] = strategy
        if strategy.name not in self.success_history:
            self.success_history[strategy.name] = []
            self.failure_count[strategy.name] = 0

    def select(self, task_type: str, context: dict = None) -> Optional[Strategy]:
        context = context or {}
        candidates = [s for s in self.strategies.values() if self._matches(s, task_type)]
        if not candidates:
            return None
        scored = [(s, self._score(s, task_type, context)) for s in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        best, best_score = scored[0]
        self.last_used[best.name] = time.time()
        return best if best_score >= best.confidence_threshold else None

    def _matches(self, strategy: Strategy, task_type: str) -> bool:
        tl = task_type.lower()
        return any(t.lower() in tl for t in strategy.tools)

    def _score(self, strategy: Strategy, task_type: str, context: dict) -> float:
        score = 0.5
        history = self.success_history.get(strategy.name, [])
        if history:
            recent = history[-10:]
            score = (score + sum(recent) / len(recent)) / 2
        last = self.last_used.get(strategy.name)
        if last:
            elapsed = time.time() - last
            if elapsed < 60:
                score += 0.15
            elif elapsed < 3600:
                score += 0.05
        failures = self.failure_count.get(strategy.name, 0)
        if failures > 0:
            score *= max(0.1, 1.0 - (failures * 0.25))
        return max(0.0, min(1.0, score))

    def record_success(self, strategy_name: str, score: float = 0.8):
        self.success_history.setdefault(strategy_name, []).append(score)
        if len(self.success_history[strategy_name]) > 100:
            self.success_history[strategy_name] = self.success_history[strategy_name][-50:]
        self.failure_count[strategy_name] = 0

    def record_failure(self, strategy_name: str):
        self.failure_count[strategy_name] = self.failure_count.get(strategy_name, 0) + 1

    def get_stats(self) -> dict:
        return {
            "strategies": len(self.strategies),
            "successes": sum(len(h) for h in self.success_history.values()),
            "failures": sum(self.failure_count.values()),
        }


_selector_instance: Optional[StrategySelector] = None


def get_selector() -> StrategySelector:
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = StrategySelector()
        _selector_instance.register(Strategy("uia", "UI Automation inspection", ["uia_get_elements", "uia_click"]))
        _selector_instance.register(Strategy("win32", "Direct Win32 input", ["win32_mouse_move", "win32_click", "win32_key_press"]))
        _selector_instance.register(Strategy("vision", "Screen vision/OCR", ["take_screenshot", "ocr_image", "read_screen"]))
        _selector_instance.register(Strategy("window", "Window management", ["win32_window_focus", "win32_window_close", "win32_window_list"]))
        _selector_instance.register(Strategy("browser", "Browser automation", ["browser_navigate", "browser_search", "browser_click"]))
    return _selector_instance


@register(
    name="select_strategy",
    description="Seleccionar la mejor estrategia para una tarea basada en historial",
    parameters={
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "description": "Tipo de tarea (ej: click, type, navigate)"},
        },
        "required": ["task_type"],
    },
    tier="premium",
)
def select_strategy(task_type: str) -> str:
    sel = get_selector()
    strategy = sel.select(task_type)
    if strategy:
        return f"Estrategia recomendada: {strategy.name} - {strategy.description}"
    return f"No hay estrategia disponible para: {task_type}"


@register(
    name="strategy_stats",
    description="Estadisticas del selector de estrategias",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def strategy_stats() -> str:
    sel = get_selector()
    s = sel.get_stats()
    return f"Estrategias: {s['strategies']}, exitos: {s['successes']}, fallos: {s['failures']}"
