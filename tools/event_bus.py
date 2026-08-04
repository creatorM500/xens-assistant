"""
event_bus.py — Pub/sub system for decoupled module communication.
Ported from Xens Omni event_bus.py. Standalone singleton.
"""
import json, logging, threading, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("xens.event_bus")

Handler = Callable[["Event"], None]


@dataclass
class Event:
    type: str
    source: str
    data: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class EventBus:
    _shared_bus = None
    _lock = threading.Lock()

    def __init__(self):
        self._subscriptions: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 200

    @classmethod
    def get_bus(cls) -> "EventBus":
        if cls._shared_bus is None:
            with cls._lock:
                if cls._shared_bus is None:
                    cls._shared_bus = cls()
        return cls._shared_bus

    def subscribe(self, event_type: str, handler: Handler):
        with self._lock:
            self._subscriptions[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler):
        with self._lock:
            try:
                self._subscriptions[event_type].remove(handler)
            except ValueError:
                pass

    def publish(self, event_type: str, source: str, data: dict | None = None):
        event = Event(type=event_type, source=source, data=data or {})
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            handlers = list(self._subscriptions.get(event_type, []))
        for h in handlers:
            try:
                h(event)
            except Exception:
                logger.exception(f"Error in handler for {event_type}")

    def emit(self, event_type: str, data: dict | None = None):
        self.publish(event_type, "system", data)

    def recent(self, limit: int = 10) -> list[Event]:
        with self._lock:
            return list(self._history[-limit:])

    def clear(self):
        with self._lock:
            self._history.clear()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "subscriptions": len(self._subscriptions),
                "history_size": len(self._history),
                "subscribers_total": sum(len(v) for v in self._subscriptions.values()),
            }


event_bus = EventBus.get_bus()
