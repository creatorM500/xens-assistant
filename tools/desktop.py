import json, subprocess, sys, base64, io, os, re, logging, time
from pathlib import Path
from .registry import register

@register(name="screenshot", description="Take a screenshot of the current screen. Returns a base64 PNG image.", tier="free")
def screenshot() -> str:
    try:
        import pyautogui
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return json.dumps({
            "success": True,
            "format": "png",
            "base64": b64,
            "size": len(buf.getvalue()),
        })
    except ImportError:
        return json.dumps({"error": "pyautogui not installed. Run: pip install pyautogui", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Screenshot failed: {e}", "success": False})

@register(name="get_clipboard", description="Read text from the system clipboard.", tier="free")
def get_clipboard() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        return json.dumps({
            "success": True,
            "content": text[:5000],
            "truncated": len(text) > 5000,
        })
    except ImportError:
        return json.dumps({"error": "pyperclip not installed. Run: pip install pyperclip", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Clipboard read failed: {e}", "success": False})

@register(name="set_clipboard", description="Write text to the system clipboard.", tier="free")
def set_clipboard(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return json.dumps({"success": True, "action": "copied", "length": len(text)})
    except ImportError:
        return json.dumps({"error": "pyperclip not installed. Run: pip install pyperclip", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Clipboard write failed: {e}", "success": False})

@register(name="get_active_window", description="Get the title of the currently active window.", tier="free")
def get_active_window() -> str:
    if sys.platform == "win32":
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            _, _, cls = win32gui.GetClassName(hwnd), None, None
            return json.dumps({"success": True, "title": title, "platform": "windows"})
        except ImportError:
            pass
        except Exception as e:
            return json.dumps({"error": f"Active window detection failed: {e}", "success": False})

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=5
            )
            app = result.stdout.strip()
            return json.dumps({"success": True, "title": app, "platform": "macos"})
        except:
            pass

    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return json.dumps({"success": True, "title": result.stdout.strip(), "platform": "linux"})
    except:
        pass

    return json.dumps({"error": "Active window detection not available on this platform", "success": False})

logger = logging.getLogger("xens.tools.desktop")

_KNOWN_APPS = {
    "discord": {"paths": [os.path.expanduser("~\\AppData\\Local\\Discord\\Update.exe"), os.path.expanduser("~\\AppData\\Local\\Discord\\app-*\\Discord.exe")], "command": "start discord"},
    "chrome": {"paths": ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe")], "command": "start chrome"},
    "firefox": {"paths": ["C:\\Program Files\\Mozilla Firefox\\firefox.exe", "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe"], "command": "start firefox"},
    "edge": {"paths": ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"], "command": "start msedge"},
    "code": {"paths": [os.path.expanduser("~\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"), "C:\\Program Files\\Microsoft VS Code\\Code.exe"], "command": "start code"},
    "terminal": {"paths": [], "command": "start cmd"},
    "powershell": {"paths": [], "command": "start powershell"},
    "notepad": {"paths": [], "command": "start notepad"},
    "explorer": {"paths": [], "command": "start explorer"},
    "spotify": {"paths": [os.path.expanduser("~\\AppData\\Roaming\\Spotify\\Spotify.exe"), "C:\\Program Files\\Spotify\\Spotify.exe"], "command": "start spotify"},
    "slack": {"paths": [os.path.expanduser("~\\AppData\\Local\\slack\\slack.exe")], "command": "start slack"},
}

@register(name="launch_app", description="Launch a Windows application by name.", tier="free")
def launch_app(name: str, url: str = "", wait: int = 3) -> str:
    if not name:
        return json.dumps({"error": "App name is required", "success": False})
    name = name.lower().strip()
    if name == "discord":
        subprocess.run("taskkill /f /im Discord.exe 2>nul", shell=True, capture_output=True)
    if name in _KNOWN_APPS:
        app = _KNOWN_APPS[name]
        for pattern in app["paths"]:
            if "*" in pattern:
                import glob
                matches = sorted(glob.glob(pattern))
                if matches:
                    exe = matches[-1]
                    if os.path.isfile(exe):
                        try:
                            args = [exe, "--processStart", "Discord.exe"] if "Update.exe" in exe else [exe]
                            subprocess.Popen(args, shell=True)
                            time.sleep(wait)
                            return json.dumps({"success": True, "app": name, "method": "path", "path": exe})
                        except:
                            continue
            else:
                if os.path.isfile(pattern):
                    try:
                        args = [pattern, "--processStart", "Discord.exe"] if "Update.exe" in pattern else [pattern]
                        subprocess.Popen(args, shell=True)
                        time.sleep(wait)
                        return json.dumps({"success": True, "app": name, "method": "path", "path": pattern})
                    except:
                        continue
        try:
            subprocess.Popen(app["command"], shell=True)
            time.sleep(min(wait, 2))
            return json.dumps({"success": True, "app": name, "method": "command"})
        except:
            pass
    try:
        result = subprocess.run(f"where {name}", capture_output=True, text=True, timeout=5, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            exe = result.stdout.strip().split("\n")[0].strip()
            if os.path.isfile(exe):
                subprocess.Popen([exe], shell=True)
                time.sleep(min(wait, 2))
                return json.dumps({"success": True, "app": name, "method": "where", "path": exe})
    except:
        pass
    try:
        subprocess.Popen(f"start {name}", shell=True)
        time.sleep(min(wait, 2))
        return json.dumps({"success": True, "app": name, "method": "start"})
    except:
        pass
    return json.dumps({"error": f"Could not find or launch '{name}'", "success": False})
