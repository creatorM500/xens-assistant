from .registry import register
"""
native_macros.py — Keyboard/mouse macro recorder.
Record, save, list, execute, delete macros using pynput.
Ported from Omni macro_recorder.py with cleanup and JSON returns.
"""
import json, logging, os, threading, time, atexit
from pathlib import Path

logger = logging.getLogger("xens.tools.native_macros")

try:
    from pynput import keyboard, mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

_DATA_DIR = Path.home() / ".ainslup" / "macros"

_SAFE_NAME_RE = "^[a-zA-Z0-9_\\- ]{1,64}$"

def _valid_name(name: str) -> bool:
    import re
    return bool(name) and len(name) <= 64 and re.match(_SAFE_NAME_RE, name) is not None

def _macro_path(name: str) -> Path:
    """Path validado dentro de _DATA_DIR (sin path traversal)."""
    if not _valid_name(name):
        raise ValueError(f"Invalid macro name: {name!r} (use letters, numbers, _ - and spaces)")
    path = _DATA_DIR / f"{name}.json"
    if not path.is_relative_to(_DATA_DIR):
        raise ValueError(f"Invalid macro name: {name!r}")
    return path

_recording = []
_recording_active = False
_listener_k = None
_listener_m = None


def _on_press(k):
    try:
        key = k.char if hasattr(k, 'char') and k.char else str(k)
        _recording.append({"type": "key_down", "key": key, "time": time.time()})
    except Exception:
        _recording.append({"type": "key_down", "key": str(k), "time": time.time()})

def _on_release(k):
    _recording.append({"type": "key_up", "key": str(k), "time": time.time()})

def _on_click(x, y, button, pressed):
    _recording.append({"type": "mouse_click", "x": x, "y": y, "button": str(button), "pressed": pressed, "time": time.time()})

def _on_scroll(x, y, dx, dy):
    _recording.append({"type": "mouse_scroll", "x": x, "y": y, "dx": dx, "dy": dy, "time": time.time()})


@register(name="macro_record", description="Start recording keyboard/mouse macro.", tier="free")
def macro_record(name: str = "") -> str:
    global _recording, _recording_active, _listener_k, _listener_m
    if not HAS_PYNPUT:
        return json.dumps({"error": "pynput not installed (pip install pynput)", "success": False})
    if _recording_active:
        return json.dumps({"error": "Already recording. Stop first (macro_stop).", "success": False})
    _recording = []
    _recording_active = True
    _listener_k = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    _listener_m = mouse.Listener(on_click=_on_click, on_scroll=_on_scroll)
    _listener_k.start()
    _listener_m.start()
    return json.dumps({"success": True, "message": f"Recording started{' as ' + name if name else ''}. Perform actions then call macro_stop."})


@register(name="macro_stop", description="Stop recording and save macro.", tier="free")
def macro_stop(name: str = "") -> str:
    global _recording_active, _listener_k, _listener_m
    if not HAS_PYNPUT:
        return json.dumps({"error": "pynput not installed", "success": False})
    if not _recording_active:
        return json.dumps({"error": "No active recording", "success": False})
    _recording_active = False
    if _listener_k:
        _listener_k.stop()
    if _listener_m:
        _listener_m.stop()
    if not _recording:
        return json.dumps({"success": True, "message": "Recording stopped (empty)"})
    import copy
    events = copy.deepcopy(_recording)
    if not name:
        name = f"macro_{int(time.time())}"
    try:
        path = _macro_path(name)
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "created": time.time(), "events": events}, indent=2), encoding="utf-8")
    return json.dumps({"success": True, "macro": name, "events": len(events)})


@register(name="macro_list", description="List saved macros.", tier="free")
def macro_list() -> str:
    if not _DATA_DIR.exists():
        return json.dumps({"success": True, "macros": [], "count": 0})
    files = sorted(f.stem for f in _DATA_DIR.iterdir() if f.suffix == ".json")
    return json.dumps({"success": True, "count": len(files), "macros": files})


@register(name="macro_play", description="Play back a recorded macro.", tier="free")
def macro_play(name: str) -> str:
    if not HAS_PYNPUT:
        return json.dumps({"error": "pynput not installed", "success": False})
    try:
        path = _macro_path(name)
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    if not path.exists():
        return json.dumps({"error": f"Macro not found: {name}", "success": False})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"error": f"Failed to read macro: {e}", "success": False})
    events = data.get("events", [])
    if not events:
        return json.dumps({"error": f"Macro '{name}' is empty", "success": False})
    from pynput.keyboard import Controller as KController, Key
    from pynput.mouse import Controller as MController, Button
    kc = KController()
    mc = MController()
    KEY_MAP = {}
    for k in dir(Key):
        if not k.startswith("_"):
            KEY_MAP[k] = getattr(Key, k)
    KEY_MAP["Key.space"] = Key.space
    KEY_MAP["Key.enter"] = Key.enter
    for i, ev in enumerate(events):
        if i > 0 and ev["time"] > events[i-1]["time"]:
            delay = ev["time"] - events[i-1]["time"]
            if delay < 2:
                time.sleep(delay)
        try:
            if ev["type"] == "key_down":
                k = ev["key"]
                if k.startswith("Key."):
                    mapped = KEY_MAP.get(k.replace("Key.", ""))
                    if mapped:
                        kc.press(mapped)
                    else:
                        kc.press(k)
                else:
                    k = k.replace("'", "")
                    if len(k) == 1:
                        kc.press(k)
            elif ev["type"] == "key_up":
                k = ev["key"]
                if k.startswith("Key."):
                    mapped = KEY_MAP.get(k.replace("Key.", ""))
                    if mapped:
                        kc.release(mapped)
                    else:
                        kc.release(k)
                else:
                    k = k.replace("'", "")
                    if len(k) == 1:
                        kc.release(k)
            elif ev["type"] == "mouse_click":
                btn = getattr(Button, ev["button"].split(".")[-1], Button.left)
                if ev["pressed"]:
                    mc.press(btn)
                else:
                    mc.release(btn)
            elif ev["type"] == "mouse_scroll":
                mc.scroll(int(ev["dx"]), int(ev["dy"]))
        except Exception:
            pass
    return json.dumps({"success": True, "macro": name, "events": len(events)})


@register(name="macro_delete", description="Delete a saved macro.", tier="free")
def macro_delete(name: str) -> str:
    try:
        path = _macro_path(name)
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    if path.exists():
        path.unlink()
        return json.dumps({"success": True, "macro": name, "action": "deleted"})
    return json.dumps({"error": f"Macro not found: {name}", "success": False})
