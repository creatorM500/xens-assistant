from .registry import register
"""
reminders.py — Timer-based reminder system.
Stores reminders in ~/.ainslup/reminders.json. Fires notifications via Toast or print.
"""
import json, logging, threading, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.reminders")

_REMINDERS_PATH = Path.home() / ".ainslup" / "reminders.json"
_reminders: list[dict] = []
_checker_thread: Optional[threading.Thread] = None
_checker_running = False
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        if _REMINDERS_PATH.exists():
            return json.loads(_REMINDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save():
    try:
        _REMINDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            _REMINDERS_PATH.write_text(json.dumps(_reminders, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save reminders: %s", e)


def _notify(title: str, message: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except ImportError:
        logger.info("REMINDER: %s — %s", title, message)


def _check_loop():
    global _checker_running
    while _checker_running:
        now = time.time()
        fired = []
        with _lock:
            for r in _reminders:
                if not r.get("fired") and r.get("timestamp", 0) <= now:
                    r["fired"] = True
                    fired.append(r)
            _reminders[:] = [r for r in _reminders if not r.get("fired") or r.get("keep", False)]
        for r in fired:
            _notify("Ainslup Reminder", r.get("message", "Reminder"))
            logger.info("Reminder fired: %s", r.get("message", ""))
        if fired:
            _save()
        time.sleep(5)


def start_checker():
    global _checker_thread, _checker_running
    if _checker_running:
        return
    _checker_running = True
    _checker_thread = threading.Thread(target=_check_loop, daemon=True)
    _checker_thread.start()
    logger.info("Reminder checker started")


def stop_checker():
    global _checker_running
    _checker_running = False


@register(name="set_reminder", description="Set a timer-based reminder. Fires a notification at the specified time.", tier="free")
def set_reminder(message: str, seconds: int = 0, minutes: int = 0, hours: int = 0,
                 at: str = "") -> str:
    global _reminders
    seconds_total = seconds + minutes * 60 + hours * 3600
    if at:
        try:
            dt = datetime.strptime(at, "%Y-%m-%d %H:%M")
            ts = dt.timestamp()
        except ValueError:
            return json.dumps({"error": "Invalid time format. Use YYYY-MM-DD HH:MM", "success": False})
    elif seconds_total > 0:
        ts = time.time() + seconds_total
    else:
        return json.dumps({"error": "Specify seconds, minutes, hours, or an absolute time (at)", "success": False})
    if not _reminders:
        with _lock:
            if not _reminders:
                _reminders[:] = _load()
    reminder = {
        "id": f"rem_{int(time.time())}",
        "message": message,
        "timestamp": ts,
        "created": datetime.now().isoformat(),
        "fired": False,
        "keep": False,
    }
    with _lock:
        _reminders.append(reminder)
    _save()
    eta = datetime.fromtimestamp(ts).isoformat()
    start_checker()
    return json.dumps({"success": True, "reminder": message, "at": eta, "id": reminder["id"]})


@register(name="list_reminders", description="List all pending reminders.", tier="free")
def list_reminders() -> str:
    global _reminders
    with _lock:
        if not _reminders:
            _reminders[:] = _load()
        pending = [r for r in _reminders if not r.get("fired")]
    return json.dumps({
        "success": True,
        "count": len(pending),
        "reminders": [
            {
                "id": r["id"],
                "message": r["message"],
                "at": datetime.fromtimestamp(r["timestamp"]).isoformat(),
            }
            for r in pending
        ]
    })


@register(name="cancel_reminder", description="Cancel a pending reminder by ID.", tier="free")
def cancel_reminder(reminder_id: str) -> str:
    global _reminders
    with _lock:
        if not _reminders:
            _reminders[:] = _load()
        before = len(_reminders)
        _reminders[:] = [r for r in _reminders if r.get("id") != reminder_id]
        removed = before - len(_reminders)
    if removed:
        _save()
        return json.dumps({"success": True, "cancelled": reminder_id})
    return json.dumps({"error": f"No reminder found with id: {reminder_id}", "success": False})
