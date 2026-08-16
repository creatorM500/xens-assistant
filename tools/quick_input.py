import os
import threading
import tkinter as tk
from tkinter import ttk
from .registry import register

BACKEND_URL = os.environ.get("XENS_BACKEND", "http://127.0.0.1:5000")


def _send_message(text: str) -> str:
    try:
        import urllib.request
        import json
        data = json.dumps({"mensaje": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKEND_URL}/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("respuesta", "(sin respuesta)")
    except Exception as e:
        return f"Error: {e}"


def _show_notification(title: str, message: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=message[:256], timeout=8)
    except Exception:
        pass


class QuickInputWindow:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Xens - Quick Input")
        self.window.geometry("420x140")
        self.window.resizable(False, False)
        self._center()
        try:
            self.window.attributes("-topmost", True)
        except Exception:
            pass
        frame = ttk.Frame(self.window, padding="12")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="What do you want to do?", font=("Segoe UI", 10)).pack(anchor=tk.W)
        self.entry = ttk.Entry(frame, font=("Segoe UI", 11))
        self.entry.pack(fill=tk.X, pady=(6, 8))
        self.entry.focus_set()
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        self.send_btn = ttk.Button(btn_frame, text="Send (Enter)", command=self._on_send)
        self.send_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="Close (Esc)", command=self.window.destroy).pack(side=tk.LEFT)
        self.status = ttk.Label(frame, text="", font=("Segoe UI", 9))
        self.status.pack(fill=tk.X, pady=(4, 0))
        self.entry.bind("<Return>", lambda e: self._on_send())
        self.entry.bind("<Escape>", lambda e: self.window.destroy())
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

    def _center(self):
        self.window.update_idletasks()
        w, h = self.window.winfo_width(), self.window.winfo_height()
        sw, sh = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        self.window.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _on_send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.send_btn.config(state=tk.DISABLED)
        self.status.config(text="Sending...")
        self.window.update()

        def do_send():
            response = _send_message(text)
            self.window.after(0, self._on_response, response)

        threading.Thread(target=do_send, daemon=True).start()

    def _on_response(self, response: str):
        self.window.destroy()
        _show_notification("Xens", response[:256])

    def run(self):
        self.window.mainloop()


@register(
    name="open_quick_input",
    description="Abrir ventana de input rapido para enviar mensaje al backend",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def open_quick_input() -> str:
    threading.Thread(target=QuickInputWindow().run, daemon=True).start()
    return "Ventana de input rapido abierta"


@register(
    name="register_hotkey",
    description="Registrar hotkey global Ctrl+Shift+X para abrir input rapido",
    parameters={
        "type": "object",
        "properties": {
            "hotkey": {"type": "string", "description": "Combinacion de teclas (default: ctrl+shift+x)"},
        },
        "required": [],
    },
    tier="free",
)
def register_hotkey(hotkey: str = "ctrl+shift+x") -> str:
    try:
        import keyboard
        if getattr(register_hotkey, "_registered", False):
            return f"Hotkey ya registrado: {hotkey}"
        keyboard.add_hotkey(
            hotkey,
            lambda: threading.Thread(target=QuickInputWindow().run, daemon=True).start(),
        )
        register_hotkey._registered = True
        return f"Hotkey {hotkey} registrado. Funciona mientras el servidor siga activo."
    except ImportError:
        return "keyboard no disponible. pip install keyboard"
