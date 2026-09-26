from .registry import register
"""
automations.py — Event-condition-action rule engine.
Self-contained (uses local EventBus from event_bus.py).
Ported from Xens Omni reactive_engine.py — no xens_engine imports.
"""
import json, logging, os, threading, time
from pathlib import Path
from typing import Any, Callable, Optional
from .event_bus import EventBus, Event

logger = logging.getLogger("xens.tools.automations")

_RULES_PATH = Path.home() / ".ainslup" / "reactive_rules.json"


class Rule:
    def __init__(
        self,
        name: str,
        event_pattern: str,
        condition: Optional[dict] = None,
        action: str = "log",
        action_config: Optional[dict] = None,
        enabled: bool = True,
    ):
        self.name = name
        self.event_pattern = event_pattern
        self.condition = condition or {}
        self.action = action
        self.action_config = action_config or {}
        self.enabled = enabled
        self.created_at = time.time()
        self.trigger_count = 0
        self.last_triggered: Optional[float] = None

    def matches(self, event: Event) -> bool:
        if not self.enabled:
            return False
        if event.type != self.event_pattern:
            return False
        for key, expected in self.condition.items():
            actual = event.data
            for part in key.split("."):
                if isinstance(actual, dict):
                    actual = actual.get(part)
                else:
                    return False
            if actual != expected:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "event_pattern": self.event_pattern,
            "condition": self.condition,
            "action": self.action,
            "action_config": self.action_config,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "trigger_count": self.trigger_count,
            "last_triggered": self.last_triggered,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        r = cls(
            name=str(d.get("name") or "unnamed"),
            event_pattern=str(d.get("event_pattern") or ""),
            condition=d.get("condition"),
            action=d.get("action", "log"),
            action_config=d.get("action_config"),
            enabled=d.get("enabled", True),
        )
        r.created_at = d.get("created_at", time.time())
        r.trigger_count = d.get("trigger_count", 0)
        r.last_triggered = d.get("last_triggered")
        return r


class AutomationEngine:
    def __init__(self, rules_path: str = str(_RULES_PATH)):
        self.bus = EventBus.get_bus()
        self.rules_path = rules_path
        self.rules: list[Rule] = []
        self._action_handlers: dict[str, Callable] = {}
        self._running = False
        self._load_rules()

    def register_action(self, name: str, handler: Callable[[Rule, Event], None]):
        self._action_handlers[name] = handler

    def add_rule(self, rule: Rule) -> bool:
        if any(r.name == rule.name for r in self.rules):
            return False
        self.rules.append(rule)
        self._save_rules()
        return True

    def remove_rule(self, name: str) -> bool:
        for r in self.rules:
            if r.name == name:
                self.rules.remove(r)
                self._save_rules()
                return True
        return False

    def get_rules(self) -> list[Rule]:
        return list(self.rules)

    def start(self):
        if self._running:
            return
        if not self._action_handlers:
            self.register_action("log", self._action_log)
        self.bus.subscribe("*", self._on_event)
        self._running = True
        logger.info("AutomationEngine started (%d rules)", len(self.rules))

    def stop(self):
        if not self._running:
            return
        self._running = False
        logger.info("AutomationEngine stopped")

    def _on_event(self, event: Event):
        if not self._running:
            return
        for rule in self.rules:
            try:
                if not rule.matches(event):
                    continue
            except Exception as e:
                logger.warning("Rule '%s' match error: %s", getattr(rule, "name", "?"), e)
                continue
            handler = self._action_handlers.get(rule.action)
            if handler:
                try:
                    handler(rule, event)
                    rule.trigger_count += 1
                    rule.last_triggered = time.time()
                    self._save_rules()
                except Exception as e:
                    logger.error("Rule '%s' error: %s", rule.name, e)

    def _action_log(self, rule: Rule, event: Event):
        logger.info("[AUTO] %s: %s -> %s", rule.name, event.type, json.dumps(event.data)[:100])

    def _load_rules(self):
        try:
            if os.path.exists(self.rules_path):
                with open(self.rules_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.rules = [Rule.from_dict(r) for r in data if isinstance(r, dict)]
        except Exception as e:
            logger.warning("Error loading rules: %s", e)

    def _save_rules(self):
        try:
            os.makedirs(os.path.dirname(self.rules_path), exist_ok=True)
            with open(self.rules_path, "w", encoding="utf-8") as f:
                json.dump([r.to_dict() for r in self.rules], f, indent=2)
        except Exception as e:
            logger.warning("Error saving rules: %s", e)


_engine: Optional[AutomationEngine] = None


def start_engine(rules_path: str = str(_RULES_PATH)) -> AutomationEngine:
    global _engine
    if _engine is None:
        _engine = AutomationEngine(rules_path)
        _engine.start()
    return _engine


def stop_engine():
    global _engine
    if _engine:
        _engine.stop()
        _engine = None


def get_engine() -> Optional[AutomationEngine]:
    return _engine


# ── Tool-callable wrapper functions ──────────────────────────────

@register(name="create_rule", description="Create an event-condition-action automation rule (Premium feature).", tier="free")
def create_rule(name: str, event_pattern: str, condition: dict = None,
                action: str = "log", action_config: dict = None) -> str:
    engine = start_engine()
    rule = Rule(name, event_pattern, condition, action, action_config)
    ok = engine.add_rule(rule)
    return json.dumps({"success": ok, "rule": name, "event_pattern": event_pattern, "action": action})


@register(name="delete_rule", description="Delete an automation rule by name.", tier="free")
def delete_rule(name: str) -> str:
    engine = get_engine()
    if not engine:
        return json.dumps({"error": "Engine not started", "success": False})
    ok = engine.remove_rule(name)
    return json.dumps({"success": ok, "rule": name})


@register(name="list_rules", description="List all automation rules and their status.", tier="free")
def list_rules() -> str:
    engine = get_engine()
    if not engine:
        return json.dumps({"success": True, "rules": [], "running": False})
    rules = engine.get_rules()
    return json.dumps({
        "success": True,
        "running": engine._running,
        "count": len(rules),
        "rules": [r.to_dict() for r in rules],
    })


@register(name="publish_event", description="Manually publish an event to the event bus (for testing automations).", tier="free")
def publish_event(event_type: str, data: dict = None) -> str:
    bus = EventBus.get_bus()
    bus.emit(event_type, data or {})
    return json.dumps({"success": True, "event": event_type})
