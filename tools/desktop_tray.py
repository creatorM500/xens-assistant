from .registry import register
"""
desktop_tray.py — System tray icon + quick HUD overlay + Windows autorun.
Ported from Omni desktop.py with cleanup and JSON returns.
"""
import json, logging, os, sys, threading, webbrowser
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.desktop_tray")

_DATA_DIR = Path.home() / ".ainslup"
_HUD_WINDOW = None
_TRAY_ICON = None


def _get_icon_path() -> str:
    base = Path(__file__).resolve().parent.parent / "assets"
    for name in ["ainslup.ico", "ainslup.png", "icon.ico", "icon.png"]:
        path = base / name
        if path.exists():
            return str(path)
    return ""


@register(name="start_tray", description="Start system tray icon.", tier="free", internal=True)
def start_tray() -> str:
    global _TRAY_ICON
    if _TRAY_ICON is not None:
        return json.dumps({"success": True, "message": "Tray already running"})
    try:
        import pystray
        from PIL import Image

        icon_path = _get_icon_path()
        image = Image.open(icon_path) if icon_path else Image.new("RGBA", (64, 64), (0, 120, 255, 255))

        def on_show(icon, item):
            show_hud()

        def on_hide(icon, item):
            hide_hud()

        def on_open_browser(icon, item):
            webbrowser.open("http://127.0.0.1:18000")

        def on_quit(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Show HUD", on_show, default=True),
            pystray.MenuItem("Hide HUD", on_hide),
            pystray.MenuItem("Open Web UI", on_open_browser),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )
        _TRAY_ICON = pystray.Icon("ainslup", image, "Ainslup Assistant", menu)
        t = threading.Thread(target=_TRAY_ICON.run, daemon=True, name="ainslup-tray")
        t.start()
        return json.dumps({"success": True, "message": "System tray started"})
    except Exception as e:
        return json.dumps({"error": f"Failed to start tray: {e}", "success": False})


@register(name="stop_tray", description="Stop system tray icon.", tier="free", internal=True)
def stop_tray() -> str:
    global _TRAY_ICON
    if _TRAY_ICON:
        try:
            _TRAY_ICON.stop()
        except Exception:
            pass
        _TRAY_ICON = None
    return json.dumps({"success": True, "message": "System tray stopped"})


@register(name="show_hud", description="Show the HUD overlay window.", tier="free", internal=True)
def show_hud() -> str:
    global _HUD_WINDOW
    if _HUD_WINDOW is not None:
        try:
            _HUD_WINDOW.show()
            return json.dumps({"success": True, "message": "HUD shown"})
        except Exception:
            _HUD_WINDOW = None
    try:
        import webview
        html = _generate_hud_html()
        def _run():
            global _HUD_WINDOW
            _HUD_WINDOW = webview.create_window(
                "Ainslup", html=html, width=380, height=500,
                frameless=True, transparent=True, always_on_top=True,
                resizable=False, easy_drag=False,
            )
            webview.start(private_mode=True)
        threading.Thread(target=_run, daemon=True, name="ainslup-hud").start()
        return json.dumps({"success": True, "message": "HUD launched"})
    except Exception as e:
        return json.dumps({"error": f"Failed to show HUD: {e}", "success": False})


@register(name="hide_hud", description="Hide the HUD overlay window.", tier="free", internal=True)
def hide_hud() -> str:
    global _HUD_WINDOW
    if _HUD_WINDOW is not None:
        try:
            _HUD_WINDOW.hide()
        except Exception:
            pass
    return json.dumps({"success": True, "message": "HUD hidden"})


@register(name="tray_status", description="Get system tray and HUD status.", tier="free", internal=True)
def tray_status() -> str:
    return json.dumps({
        "success": True,
        "tray": _TRAY_ICON is not None,
        "hud": _HUD_WINDOW is not None,
    })


@register(name="set_autorun", description="Enable or disable Windows autorun.", tier="free", internal=True)
def set_autorun(enable: bool = True) -> str:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enable:
            exe = sys.executable
            winreg.SetValueEx(key, "Ainslup", 0, winreg.REG_SZ, f'"{exe}" "-m" "ainslup_assistant"')
            winreg.CloseKey(key)
            return json.dumps({"success": True, "message": "Autorun enabled"})
        else:
            try:
                winreg.DeleteValue(key, "Ainslup")
            except Exception:
                try:
                    winreg.DeleteValue(key, "XensPro")  # legacy
                except Exception:
                    pass
            winreg.CloseKey(key)
            return json.dumps({"success": True, "message": "Autorun disabled"})
    except Exception as e:
        return json.dumps({"error": f"Autorun failed: {e}", "success": False})


def _generate_hud_html() -> str:
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:rgba(10,10,20,0.75);color:#e0e0e0;padding:20px;border-radius:16px;backdrop-filter:blur(20px);height:100vh;overflow-y:auto;user-select:none}
.header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.logo{width:36px;height:36px;background:linear-gradient(135deg,#0066ff,#00ccff);border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;color:white}
.title{font-size:18px;font-weight:600}
.subtitle{font-size:12px;color:#888;margin-top:2px}
.section{margin-bottom:16px}
.section-title{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#666;margin-bottom:8px}
.card{background:rgba(255,255,255,0.04);border-radius:10px;padding:12px;margin-bottom:6px;border:1px solid rgba(255,255,255,0.03)}
.card-label{font-size:11px;color:#888}
.card-value{font-size:14px;font-weight:500;margin-top:2px}
.footer{font-size:10px;color:#444;text-align:center;margin-top:16px}
</style></head><body>
<div class="header"><div class="logo">A</div><div><div class="title">Ainslup</div><div class="subtitle" id="statusText">Running</div></div></div>
<div class="section"><div class="section-title">Now</div>
<div class="card"><div class="card-label">Time</div><div class="card-value" id="clock">--:--</div></div>
<div class="card"><div class="card-label">Active Window</div><div class="card-value" id="activeWindow">--</div></div></div>
<div class="footer">Ainslup Pro</div>
<script>
function updateClock(){var n=new Date();document.getElementById('clock').textContent=n.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'})}
updateClock();setInterval(updateClock,1000);
</script></body></html>"""
