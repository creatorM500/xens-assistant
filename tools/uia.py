from .registry import register
"""
uia.py — Windows UI Automation via uiautomation package.
Element-level control: find, click, type, read elements within windows.
Also provides native Win32 mouse/keyboard/window control as fallback.
Ported from Omni app_automation.py + win32_input.py with cleanup.
"""
import ctypes, ctypes.wintypes, json, logging, time
from typing import Optional

logger = logging.getLogger("xens.tools.uia")

try:
    import uiautomation as uia
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

try:
    user32 = ctypes.windll.user32
    HAS_USER32 = True
except Exception:
    HAS_USER32 = False


# ─── Win32 API Constants ────────────────────────────────────────
_SW_RESTORE = 9
_SW_MINIMIZE = 6
_SW_SHOWMAXIMIZED = 3
_VK_MAP = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "backspace": 0x08,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "space": 0x20, "ctrl": 0x11,
    "alt": 0x12, "shift": 0x10,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    ".": 0xBE, ",": 0xBC, ";": 0xBA, "'": 0xDE, "`": 0xC0,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    "/": 0xBF,
}

# ─── Win32 Mouse ────────────────────────────────────────────────

@register(name="win32_mouse_move", description="Move the mouse cursor to coordinates.", tier="free")
def win32_mouse_move(x: int, y: int) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    user32.SetCursorPos(x, y)
    return json.dumps({"success": True, "action": "mouse_move", "x": x, "y": y})

@register(name="win32_mouse_click", description="Click mouse button (left/right/double) at optional coordinates.", tier="free")
def win32_mouse_click(button: str = "left", x: int = None, y: int = None) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    if x is not None and y is not None:
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
    if button == "left":
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    elif button == "right":
        user32.mouse_event(0x0008, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(0x0010, 0, 0, 0, 0)
    elif button == "double":
        for _ in range(2):
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.02)
    else:
        return json.dumps({"error": f"Unknown button: {button}", "success": False})
    return json.dumps({"success": True, "action": f"{button}_click"})

@register(name="win32_mouse_pos", description="Get current mouse cursor position.", tier="free")
def win32_mouse_pos() -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return json.dumps({"success": True, "x": pt.x, "y": pt.y})

# ─── Win32 Keyboard ─────────────────────────────────────────────

def _send_key_down(vk: int):
    user32.keybd_event(vk, 0, 0, 0)

def _send_key_up(vk: int):
    user32.keybd_event(vk, 0, 2, 0)

@register(name="win32_key_press", description="Press and release a single key.", tier="free")
def win32_key_press(key: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    vk = _VK_MAP.get(key.lower().strip())
    if vk is None:
        return json.dumps({"error": f"Unknown key: {key}", "success": False})
    _send_key_down(vk)
    time.sleep(0.02)
    _send_key_up(vk)
    return json.dumps({"success": True, "action": "key_press", "key": key})

@register(name="win32_key_combo", description="Press a combination of keys (e.g. ctrl, c, alt, tab).", tier="free")
def win32_key_combo(*keys: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    vks = []
    for k in keys:
        vk = _VK_MAP.get(k.lower().strip())
        if vk is None:
            return json.dumps({"error": f"Unknown key: {k}", "success": False})
        vks.append(vk)
    for vk in vks:
        _send_key_down(vk)
        time.sleep(0.02)
    for vk in reversed(vks):
        _send_key_up(vk)
        time.sleep(0.02)
    return json.dumps({"success": True, "action": "key_combo", "keys": list(keys)})

_SYMBOL_MAP = {
    "!": (0x31, True), "@": (0x32, True), "#": (0x33, True), "$": (0x34, True),
    "%": (0x35, True), "^": (0x36, True), "&": (0x37, True), "*": (0x38, True),
    "(": (0x39, True), ")": (0x30, True),
    "_": (0xBD, True), "+": (0xBB, True), "{": (0xDB, True), "}": (0xDD, True),
    "|": (0xDC, True), ":": (0xBA, True), '"': (0xDE, True), "<": (0xBC, True),
    ">": (0xBE, True), "?": (0xBF, True), "~": (0xC0, True),
}

@register(name="win32_type", description="Type text using keyboard simulation.", tier="free")
def win32_type(text: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    typed = 0
    for ch in text:
        vk = None
        shift = False
        if ch.isalpha():
            vk = 0x41 + (ord(ch.lower()) - ord("a"))
            shift = ch.isupper()
        elif ch in _VK_MAP:
            vk = _VK_MAP[ch]
        elif ch in _SYMBOL_MAP:
            vk, shift = _SYMBOL_MAP[ch]
        if vk is None:
            continue
        if shift:
            _send_key_down(0x10)
        _send_key_down(vk)
        time.sleep(0.005)
        _send_key_up(vk)
        if shift:
            _send_key_up(0x10)
        typed += 1
        time.sleep(0.005)
    return json.dumps({"success": True, "action": "type", "length": typed})

# ─── Win32 Window Control ───────────────────────────────────────

def _find_window(title: str) -> Optional[int]:
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        return hwnd
    found = []
    def enum_cb(h, _):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        if title.lower() in buf.value.lower():
            found.append(h)
        return True
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(enum_proc(enum_cb), 0)
    return found[0] if found else None

@register(name="win32_window_focus", description="Focus a window by title.", tier="free")
def win32_window_focus(title: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    hwnd = _find_window(title)
    if not hwnd:
        return json.dumps({"error": f"Window not found: {title}", "success": False})
    user32.ShowWindow(hwnd, _SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return json.dumps({"success": True, "action": "focus", "window": title})

@register(name="win32_window_close", description="Close a window by title.", tier="free")
def win32_window_close(title: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    hwnd = _find_window(title)
    if not hwnd:
        return json.dumps({"error": f"Window not found: {title}", "success": False})
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    return json.dumps({"success": True, "action": "close", "window": title})

@register(name="win32_window_minimize", description="Minimize a window by title.", tier="free")
def win32_window_minimize(title: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    hwnd = _find_window(title)
    if not hwnd:
        return json.dumps({"error": f"Window not found: {title}", "success": False})
    user32.ShowWindow(hwnd, _SW_MINIMIZE)
    return json.dumps({"success": True, "action": "minimize", "window": title})

@register(name="win32_window_maximize", description="Maximize a window by title.", tier="free")
def win32_window_maximize(title: str) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    hwnd = _find_window(title)
    if not hwnd:
        return json.dumps({"error": f"Window not found: {title}", "success": False})
    user32.ShowWindow(hwnd, _SW_SHOWMAXIMIZED)
    return json.dumps({"success": True, "action": "maximize", "window": title})

@register(name="win32_window_move", description="Move/resize a window by title.", tier="free")
def win32_window_move(title: str, x: int, y: int, width: int = None, height: int = None) -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    hwnd = _find_window(title)
    if not hwnd:
        return json.dumps({"error": f"Window not found: {title}", "success": False})
    if width is not None and height is not None:
        user32.MoveWindow(hwnd, x, y, width, height, True)
    else:
        user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)
    return json.dumps({"success": True, "action": "move", "window": title})

@register(name="win32_window_list", description="List all visible windows with position.", tier="free")
def win32_window_list() -> str:
    if not HAS_USER32:
        return json.dumps({"error": "Win32 API not available", "success": False})
    windows = []
    def enum_cb(h, _):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        if buf.value:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(rect))
            windows.append({"title": buf.value, "left": rect.left, "top": rect.top,
                           "width": rect.right - rect.left, "height": rect.bottom - rect.top})
        return True
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(enum_proc(enum_cb), 0)
    return json.dumps({"success": True, "count": len(windows), "windows": windows[:30]})

# ─── UIA Element-Level Control ──────────────────────────────────

def _get_window(title: str):
    if not HAS_UIA:
        return None
    try:
        win = uia.WindowControl(searchDepth=1, Name=title)
        if win.Exists(maxSearchSeconds=2):
            return win
    except Exception:
        pass
    # Fallback: coincidencia parcial del título (ej. "Opera" -> "AINSLUP — Opera")
    try:
        for w in uia.GetRootControl().GetChildren():
            try:
                if title.lower() in (w.Name or "").lower():
                    return w
            except Exception:
                continue
    except Exception:
        pass
    return None

@register(name="uia_get_elements", description="List UI elements within a window (UIA).", tier="free")
def uia_get_elements(window_title: str) -> str:
    if not HAS_UIA:
        return json.dumps({"error": "uiautomation not installed (pip install uiautomation)", "success": False})
    try:
        win = _get_window(window_title)
        if not win:
            return json.dumps({"error": f"Window not found: {window_title}", "success": False})
        win.SetFocus()
        time.sleep(0.3)
        elements = []
        seen = set()
        def walk(control, depth=0):
            if depth > 6:
                return
            try:
                ctype_name = control.ControlTypeName
                cname = control.Name
            except Exception:
                return
            if ctype_name in (
                "ButtonControl", "EditControl", "TextControl", "ComboBoxControl",
                "ListItemControl", "HyperlinkControl", "CheckBoxControl", "RadioButtonControl",
                "TabItemControl", "MenuItemControl", "TreeItemControl",
                "SliderControl", "ToolBarControl", "PaneControl",
            ):
                name = cname
                ctype = ctype_name.replace("Control", "")
                if name:
                    key = (ctype, name)
                    if key in seen:
                        return
                    seen.add(key)
                    rect = None
                    try:
                        r = control.BoundingRectangle
                        if r:
                            rect = {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}
                    except Exception:
                        pass
                    elements.append({"type": ctype, "name": name, "rect": rect})
            try:
                children = control.GetChildren()
            except Exception:
                return
            for child in children:
                walk(child, depth + 1)
        walk(win)
        return json.dumps({"success": True, "window": window_title, "count": len(elements), "elements": elements})
    except Exception as e:
        return json.dumps({"error": f"Failed to get elements: {e}", "success": False})

@register(name="uia_click", description="Click a UI element by name within a window (UIA).", tier="free")
def uia_click(window_title: str, element_name: str) -> str:
    if not HAS_UIA:
        return json.dumps({"error": "uiautomation not installed", "success": False})
    try:
        win = _get_window(window_title)
        if not win:
            return json.dumps({"error": f"Window not found: {window_title}", "success": False})
        win.SetFocus()
        time.sleep(0.3)
        found = win.FindControl(Name=element_name)
        if found:
            found.Click()
            return json.dumps({"success": True, "action": "click", "element": element_name})
        button = win.ButtonControl(Name=element_name)
        if button.Exists(maxSearchSeconds=1):
            button.Click()
            return json.dumps({"success": True, "action": "click", "element": element_name})
        return json.dumps({"error": f"Element not found: {element_name}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Click failed: {e}", "success": False})

@register(name="uia_type", description="Type text into a field by name within a window (UIA).", tier="free")
def uia_type(window_title: str, field_name: str, text: str) -> str:
    if not HAS_UIA:
        return json.dumps({"error": "uiautomation not installed", "success": False})
    try:
        win = _get_window(window_title)
        if not win:
            return json.dumps({"error": f"Window not found: {window_title}", "success": False})
        win.SetFocus()
        time.sleep(0.3)
        edit = win.EditControl(Name=field_name)
        if edit.Exists(maxSearchSeconds=1):
            edit.Click()
            time.sleep(0.1)
            edit.SendKeys("{Ctrl}a", waitTime=0.1)
            edit.SendKeys(text, waitTime=0.05)
            return json.dumps({"success": True, "action": "type", "field": field_name, "length": len(text)})
        return json.dumps({"error": f"Field not found: {field_name}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Type failed: {e}", "success": False})

@register(name="uia_get_text", description="Read value/state of a UI element (UIA).", tier="free")
def uia_get_text(window_title: str, element_name: str) -> str:
    if not HAS_UIA:
        return json.dumps({"error": "uiautomation not installed", "success": False})
    try:
        win = _get_window(window_title)
        if not win:
            return json.dumps({"error": f"Window not found: {window_title}", "success": False})
        found = win.FindControl(Name=element_name)
        if found:
            info = {"name": element_name, "type": found.ControlTypeName}
            try:
                r = found.BoundingRectangle
                if r:
                    info["rect"] = {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}
            except Exception:
                pass
            try:
                info["enabled"] = found.IsEnabled
            except Exception:
                pass
            try:
                val = found.GetValuePattern().Value
                if val:
                    info["value"] = val[:500]
            except Exception:
                pass
            return json.dumps({"success": True, **info})
        return json.dumps({"error": f"Element not found: {element_name}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Read failed: {e}", "success": False})
