import json, time, logging, base64, io

logger = logging.getLogger("xens.tools.computer")

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

SCREENSHOT_MAX_WIDTH = 1280
SCREENSHOT_QUALITY = 70

VISUAL_ACTIONS = {"click", "double_click", "right_click", "type", "hotkey", "shortcut",
                  "drag", "open_start", "win_run", "alt_tab", "screenshot"}


def _take_screenshot():
    img = pyautogui.screenshot()
    w, h = img.size
    if w > SCREENSHOT_MAX_WIDTH:
        ratio = SCREENSHOT_MAX_WIDTH / w
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=SCREENSHOT_QUALITY, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {
        "format": "jpeg", "quality": SCREENSHOT_QUALITY,
        "base64": b64,
        "width": img.width, "height": img.height,
        "size": len(buf.getvalue()),
    }


_SCREENSHOT_ACTIONS = {"click", "double_click", "right_click", "type",
                       "hotkey", "shortcut", "drag", "open_start", "win_run",
                       "alt_tab", "screenshot"}


def _exec(action: str, x=None, y=None, text="", key="", keys=None,
          clicks=1, button="left", amount=3):
    if action == "screenshot":
        return {"success": True, "action": "screenshot", **_take_screenshot()}

    if action == "mouse_move":
        if x is None or y is None:
            return {"error": "x and y required", "success": False, "action": action}
        pyautogui.moveTo(x, y, duration=0.1)
        return {"success": True, "action": "mouse_move", "x": x, "y": y}

    if action == "click":
        if x is not None and y is not None:
            pyautogui.click(x, y, clicks=clicks, button=button)
        else:
            pyautogui.click(clicks=clicks, button=button)
        return {"success": True, "action": "click", "x": x, "y": y, "button": button, "clicks": clicks}

    if action == "right_click":
        if x is not None and y is not None:
            pyautogui.rightClick(x, y)
        else:
            pyautogui.rightClick()
        return {"success": True, "action": "right_click"}

    if action == "double_click":
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()
        return {"success": True, "action": "double_click"}

    if action == "type":
        if not text:
            return {"error": "text required", "success": False, "action": action}
        pyautogui.write(text, interval=0.003)
        return {"success": True, "action": "type", "length": len(text)}

    if action in ("keypress", "press"):
        if key:
            pyautogui.press(key)
            return {"success": True, "action": action, "key": key}
        if keys:
            for k in keys:
                pyautogui.press(k)
            return {"success": True, "action": action, "keys": keys}
        return {"error": "key or keys required", "success": False, "action": action}

    if action in ("hotkey", "shortcut"):
        if not keys or len(keys) < 1:
            return {"error": "keys required", "success": False, "action": action}
        pyautogui.hotkey(*keys)
        return {"success": True, "action": action, "keys": keys}

    if action == "scroll":
        pyautogui.scroll(amount)
        return {"success": True, "action": "scroll", "amount": amount}

    if action == "position":
        px, py = pyautogui.position()
        return {"success": True, "action": "position", "x": px, "y": py}

    if action == "screen_size":
        w, h = pyautogui.size()
        return {"success": True, "action": "screen_size", "width": w, "height": h}

    if action == "drag":
        if x is None or y is None:
            return {"error": "x and y required", "success": False, "action": action}
        pyautogui.drag(x, y, duration=0.2, button=button)
        return {"success": True, "action": "drag", "x": x, "y": y, "button": button}

    if action == "open_start":
        pyautogui.hotkey("win")
        time.sleep(0.3)
        return {"success": True, "action": "open_start"}

    if action == "win_run":
        pyautogui.hotkey("win", "r")
        time.sleep(0.2)
        return {"success": True, "action": "win_run"}

    if action == "alt_tab":
        pyautogui.hotkey("alt", "tab")
        return {"success": True, "action": "alt_tab"}

    if action == "sleep":
        secs = max(0.5, min(amount or 2, 30))
        time.sleep(secs)
        return {"success": True, "action": "sleep", "seconds": secs}

    valid = ["screenshot", "mouse_move", "click", "right_click", "double_click",
             "type", "keypress", "hotkey", "shortcut", "press", "scroll",
             "position", "screen_size", "drag", "open_start", "win_run", "alt_tab", "sleep"]
    return {"error": f"Unknown action '{action}'. Valid: {', '.join(valid)}",
            "success": False, "action": action}


def computer_use(action: str = "", x: int = None, y: int = None, text: str = "",
                 key: str = "", keys: list = None, clicks: int = 1,
                 button: str = "left", amount: int = 3,
                 actions: list = None) -> str:
    if not HAS_PYAUTOGUI:
        return json.dumps({"error": "pyautogui not installed. Run: pip install pyautogui",
                           "success": False})

    try:
        if actions:
            results = []
            final_screenshot = None
            for i, a in enumerate(actions):
                if not isinstance(a, dict):
                    results.append({"error": f"action[{i}] must be a dict", "success": False})
                    continue
                act = a.get("action", "")
                r = _exec(
                    act,
                    x=a.get("x"), y=a.get("y"),
                    text=a.get("text", ""),
                    key=a.get("key", ""),
                    keys=a.get("keys"),
                    clicks=a.get("clicks", 1),
                    button=a.get("button", "left"),
                    amount=a.get("amount", 3),
                )
                results.append(r)
                if act in _SCREENSHOT_ACTIONS:
                    final_screenshot = _take_screenshot()
            out = {"success": True, "action": "batch", "count": len(actions), "results": results}
            if final_screenshot:
                out["screenshot"] = final_screenshot
            return json.dumps(out)

        r = _exec(action, x, y, text, key, keys, clicks, button, amount)
        if action in _SCREENSHOT_ACTIONS:
            r["screenshot"] = _take_screenshot()
        return json.dumps(r)

    except pyautogui.PyAutoGUIException as e:
        return json.dumps({"error": f"Computer control error: {e}", "success": False, "action": action})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False, "action": action})
