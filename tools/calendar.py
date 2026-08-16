from .registry import register
"""
calendar.py — Local calendar manager.
Events stored in ~/.xens/calendar.json. Simple JSON-based storage.
Supports Google/Outlook via config (extensible).
Ported from Xens Omni calendar_client.py with path cleanup and JSON returns.
"""
import json, logging, os, time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.calendar")

_CAL_PATH = Path.home() / ".xens" / "calendar.json"
_CAL_CONFIG_PATH = Path.home() / ".xens" / "calendar_config.json"

def _load_events() -> list:
    try:
        if _CAL_PATH.exists():
            return json.loads(_CAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_events(events: list):
    try:
        _CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CAL_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def _load_config() -> dict:
    try:
        if _CAL_CONFIG_PATH.exists():
            return json.loads(_CAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"provider": "local"}

@register(name="create_event", description="Create a calendar event locally.", tier="free")
def create_event(title: str, date: str, time_str: str = "", duration_min: int = 60, description: str = "") -> str:
    events = _load_events()
    event = {
        "id": f"evt_{int(time.time())}",
        "title": title,
        "date": date,
        "time": time_str,
        "duration_min": duration_min,
        "description": description,
        "created": datetime.now().isoformat(),
    }
    events.append(event)
    _save_events(events)
    return json.dumps({"success": True, "event": event})

@register(name="list_events", description="List upcoming calendar events.", tier="free")
def list_events(limit: int = 10) -> str:
    events = _load_events()
    if not events:
        return json.dumps({"success": True, "events": [], "note": "No events"})
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [e for e in events if (e.get("date") or "") >= today]
    upcoming.sort(key=lambda e: e.get("date", ""))
    upcoming = upcoming[:limit]
    return json.dumps({"success": True, "count": len(upcoming), "events": upcoming})

@register(name="delete_event", description="Delete calendar event(s) by title or event_id.", tier="free")
def delete_event(title: str = "", event_id: str = "") -> str:
    events = _load_events()
    before = len(events)
    if event_id:
        events = [e for e in events if e.get("id") != event_id]
    elif title:
        events = [e for e in events if title.lower() not in (e.get("title") or "").lower()]
    else:
        return json.dumps({"error": "Specify title or event_id", "success": False})
    _save_events(events)
    removed = before - len(events)
    return json.dumps({"success": True, "removed": removed})

@register(name="configure_calendar", description="Set calendar provider (local, google, outlook).", tier="free", internal=True)
def configure_calendar(provider: str = "local", api_key: str = "", calendar_id: str = "") -> str:
    cfg = {"provider": provider}
    if api_key:
        cfg["api_key"] = api_key
    if calendar_id:
        cfg["calendar_id"] = calendar_id
    try:
        _CAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CAL_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass
    return json.dumps({"success": True, "provider": provider})
