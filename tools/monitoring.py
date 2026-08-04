from .registry import register
"""
monitoring.py — Unified system monitoring module.
Combines observer (WinEvent + idle), system_monitor (window polling + clipboard),
presence_tracker (away/present state machine), and notification_monitor (PowerShell toast capture).
"""
import ctypes
import ctypes.wintypes
import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from typing import Optional
from .event_bus import EventBus

logger = logging.getLogger("xens.tools.monitoring")

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0002
WINEVENT_SKIPOWNPROCESS = 0x0004
IDLE_THRESHOLD = 120
POLL_TITLE_INTERVAL = 2
POLL_IDLE_INTERVAL = 5

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
    ctypes.wintypes.HWND, ctypes.wintypes.LONG, ctypes.wintypes.LONG,
    ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def _get_idle_seconds() -> int:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        return (kernel32.GetTickCount() - lii.dwTime) // 1000
    return 0


def _get_window_info(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or ""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pid_val = pid.value
    proc_name = ""
    try:
        proc_handle = kernel32.OpenProcess(0x0410, False, pid_val)
        if proc_handle:
            exe_buf = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            kernel32.QueryFullProcessImageNameW(proc_handle, 0, exe_buf, ctypes.byref(size))
            kernel32.CloseHandle(proc_handle)
            proc_name = os.path.basename(exe_buf.value) if exe_buf.value else ""
    except Exception:
        pass
    return title, proc_name, pid_val


TOAST_PS_SCRIPT = r"""
Add-Type -AssemblyName UIAutomationClient
$root = [Automation.AutomationElement]::RootElement
$cond = New-Object Automation.PropertyCondition([Automation.AutomationElement]::NameProperty, '*')
$all = $root.FindAll([Automation.TreeScope]::Children, $cond)
$results = @()
$skip = @('Start','Taskbar','Desktop','Program Manager','Notification Overflow')
foreach ($e in $all) {
    $name = $e.Current.Name
    $cn = $e.Current.ClassName
    if ($name.Length -gt 3 -and $skip -notcontains $name) {
        $results += @{app=$cn; title=$name; time=(Get-Date -Format 'o')}
    }
}
if ($results.Count -gt 0) { ConvertTo-Json $results -Compress }
"""

_PS_SCRIPT_PATH = os.path.join(tempfile.gettempdir(), "xens_toast.ps1")


class SystemMonitor:
    def __init__(self):
        self._running_observer = False
        self._stop = threading.Event()
        self._hook = None
        self._prev_app = ""
        self._prev_title = ""
        self._prev_pid = 0
        self._prev_switch = 0.0
        self._is_idle = False

        self._running_sysmon = False
        self._sysmon_thread: Optional[threading.Thread] = None
        self._last_active_window = ""
        self._last_clipboard = ""
        self._window_history = []
        self._clipboard_history = []

        self._running_presence = False
        self._presence_thread: Optional[threading.Thread] = None
        self._is_away = False
        self._away_since: Optional[float] = None
        self._away_threshold = 120.0

        self._running_notif = False
        self._notif_thread: Optional[threading.Thread] = None
        self._known_ids: set = set()
        self._notifications: list = []

        self._bus = EventBus.get_bus()

    # ------------------------------------------------------------------ #
    #  Observer (WinEvent + idle)
    # ------------------------------------------------------------------ #

    def start_observer(self):
        if self._running_observer:
            return
        self._running_observer = True
        self._stop.clear()
        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
            None, self._foreground_changed, 0, 0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        threading.Thread(target=self._msg_loop, daemon=True, name="obs-msg").start()
        threading.Thread(target=self._title_loop, daemon=True, name="obs-title").start()
        threading.Thread(target=self._idle_loop, daemon=True, name="obs-idle").start()
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            title, proc, pid = _get_window_info(hwnd)
            self._prev_app, self._prev_title, self._prev_pid = proc, title, pid
        logger.info("Observer started")

    def stop_observer(self):
        if not self._running_observer:
            return
        self._running_observer = False
        self._stop.set()
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        logger.info("Observer stopped")

    @WINEVENTPROC
    def _foreground_changed(self, hook, event, hwnd, id_obj, id_child, thread, time_ms):
        if event != EVENT_SYSTEM_FOREGROUND or not hwnd:
            return
        title, proc, pid = _get_window_info(hwnd)
        if not proc:
            return
        now = time.time()
        if proc != self._prev_app:
            self._bus.emit("app.switch", {"app": proc, "title": title, "pid": pid,
                                           "duration": now - self._prev_switch if self._prev_switch else 0})
            self._prev_app, self._prev_title, self._prev_pid = proc, title, pid
            self._prev_switch = now

    def _msg_loop(self):
        msg = ctypes.wintypes.MSG()
        while not self._stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _title_loop(self):
        while not self._stop.is_set():
            self._stop.wait(POLL_TITLE_INTERVAL)
            if self._stop.is_set():
                break
            try:
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    continue
                title, proc, pid = _get_window_info(hwnd)
                if not proc:
                    continue
                if proc == self._prev_app and title != self._prev_title:
                    self._bus.emit("app.title_change", {"app": proc, "title": title, "pid": pid})
                    self._prev_title = title
                elif proc != self._prev_app:
                    self._prev_app, self._prev_title, self._prev_pid = proc, title, pid
            except Exception:
                pass

    def _idle_loop(self):
        while not self._stop.is_set():
            self._stop.wait(POLL_IDLE_INTERVAL)
            if self._stop.is_set():
                break
            try:
                secs = _get_idle_seconds()
                prev = self._is_idle
                self._is_idle = secs >= IDLE_THRESHOLD
                if self._is_idle and not prev:
                    self._bus.emit("user.idle", {"seconds": secs})
                elif not self._is_idle and prev:
                    self._bus.emit("user.active", {"seconds": secs})
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  System monitor (window polling + clipboard)
    # ------------------------------------------------------------------ #

    def start_sysmon(self):
        if self._running_sysmon:
            return
        self._running_sysmon = True
        self._sysmon_thread = threading.Thread(target=self._sysmon_loop, daemon=True, name="sysmon")
        self._sysmon_thread.start()

    def _feed_proactive_window(self, title: str):
        try:
            from .proactive import get_engine as _get_proactive
            eng = _get_proactive()
            if eng._running:
                eng.observe_window(title)
        except Exception:
            pass

    def _feed_proactive_clipboard(self, text: str):
        try:
            from .proactive import get_engine as _get_proactive
            eng = _get_proactive()
            if eng._running:
                eng.observe_clipboard(text)
        except Exception:
            pass

    def stop_sysmon(self):
        self._running_sysmon = False

    def _sysmon_loop(self):
        while self._running_sysmon:
            try:
                self._check_window()
                self._check_clipboard()
            except Exception:
                pass
            time.sleep(2.0)

    def _check_window(self):
        try:
            buf = ctypes.create_unicode_buffer(512)
            hwnd = user32.GetForegroundWindow()
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value
            if title and title != self._last_active_window:
                self._last_active_window = title
                self._window_history.append({"title": title, "ts": time.time()})
                if len(self._window_history) > 100:
                    self._window_history = self._window_history[-100:]
                self._feed_proactive_window(title)
        except Exception:
            pass

    def _check_clipboard(self):
        try:
            if user32.GetOpenClipboardWindow():
                return
            if not user32.OpenClipboard(0):
                return
            try:
                cf_text = 13
                handle = user32.GetClipboardData(cf_text)
                if handle:
                    ptr = ctypes.windll.kernel32.GlobalLock(handle)
                    if ptr:
                        text = ctypes.c_char_p(ptr).value
                        ctypes.windll.kernel32.GlobalUnlock(handle)
                        if text:
                            decoded = text.decode("utf-8", errors="replace")[:500]
                            if decoded and decoded != self._last_clipboard:
                                self._last_clipboard = decoded
                                self._clipboard_history.append({"text": decoded, "ts": time.time()})
                                if len(self._clipboard_history) > 50:
                                    self._clipboard_history = self._clipboard_history[-50:]
                                self._feed_proactive_clipboard(decoded)
            finally:
                user32.CloseClipboard()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Presence tracker (away/present state machine)
    # ------------------------------------------------------------------ #

    def start_presence(self):
        if self._running_presence:
            return
        self._running_presence = True
        self._presence_thread = threading.Thread(target=self._presence_loop, daemon=True, name="presence")
        self._presence_thread.start()

    def stop_presence(self):
        self._running_presence = False

    @property
    def is_away(self) -> bool:
        return self._is_away

    @property
    def away_duration(self) -> float:
        if self._away_since and self._is_away:
            return time.time() - self._away_since
        return 0.0

    def _presence_loop(self):
        while self._running_presence:
            idle = _get_idle_seconds()
            if idle >= self._away_threshold and not self._is_away:
                self._is_away = True
                self._away_since = time.time()
            elif idle < self._away_threshold and self._is_away:
                self._is_away = False
                self._away_since = None
            time.sleep(5.0)

    # ------------------------------------------------------------------ #
    #  Notification monitor (PowerShell toast capture)
    # ------------------------------------------------------------------ #

    def start_notif_monitor(self):
        if self._running_notif or platform.system() != "Windows":
            return
        self._running_notif = True
        self._write_ps_script()
        self._notif_thread = threading.Thread(target=self._notif_loop, daemon=True, name="notif-mon")
        self._notif_thread.start()

    def stop_notif_monitor(self):
        self._running_notif = False

    def _write_ps_script(self):
        try:
            with open(_PS_SCRIPT_PATH, "w", encoding="utf-8") as f:
                f.write(TOAST_PS_SCRIPT)
        except Exception:
            pass

    def _notif_loop(self):
        while self._running_notif:
            try:
                self._check_toasts()
            except Exception:
                pass
            time.sleep(5.0)

    def _check_toasts(self):
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", _PS_SCRIPT_PATH],
                capture_output=True, timeout=10, text=True,
            )
            raw = result.stdout.strip()
            if not raw:
                return
            entries = json.loads(raw) if raw.startswith("[") else [json.loads(raw)]
        except Exception:
            return
        for entry in entries:
            nid = f"{entry.get('app','')}|{entry.get('title','')}"
            if nid in self._known_ids:
                continue
            self._known_ids.add(nid)
            if len(self._known_ids) > 500:
                self._known_ids = set(list(self._known_ids)[-250:])
            app = entry.get("app", "sistema") or "sistema"
            title = entry.get("title", "").strip()
            if len(title) < 4:
                continue
            notif = {"app": app, "title": title, "timestamp": entry.get("time", datetime.now().isoformat())}
            self._notifications.append(notif)
            if len(self._notifications) > 200:
                self._notifications = self._notifications[-200:]

    # ------------------------------------------------------------------ #
    #  Query methods
    # ------------------------------------------------------------------ #

    def get_idle_seconds(self) -> int:
        return _get_idle_seconds()

    def is_user_idle(self) -> bool:
        return self._is_idle

    def get_system_status(self) -> dict:
        return {
            "active_window": self._last_active_window,
            "windows_seen": len(self._window_history),
            "clips_seen": len(self._clipboard_history),
        }

    def presence_status(self) -> dict:
        return {
            "is_away": self._is_away,
            "away_seconds": self.away_duration,
            "threshold": self._away_threshold,
        }

    def get_notifications(self) -> list:
        return list(self._notifications)

    # ------------------------------------------------------------------ #
    #  Status snapshots
    # ------------------------------------------------------------------ #

    def observer_status(self) -> str:
        return json.dumps({
            "success": True, "running": self._running_observer,
            "idle": self._is_idle, "idle_seconds": _get_idle_seconds(),
            "active_app": self._prev_app, "active_title": self._prev_title,
        })

    def monitoring_status(self) -> str:
        obs_running = self._running_observer
        sys_running = self._running_sysmon
        pres_running = self._running_presence
        notif_running = self._running_notif
        idle_secs = _get_idle_seconds()
        return json.dumps({
            "success": True,
            "observer": obs_running,
            "system_monitor": sys_running,
            "presence_tracker": pres_running,
            "notification_monitor": notif_running,
            "idle": self._is_idle,
            "idle_seconds": idle_secs,
            "is_away": self._is_away,
            "away_seconds": self.away_duration,
            "active_app": self._prev_app,
            "active_title": self._prev_title,
            "active_window": self._last_active_window,
            "windows_seen": len(self._window_history),
            "clips_seen": len(self._clipboard_history),
            "notifications_captured": len(self._notifications),
        })

    # ------------------------------------------------------------------ #
    #  Unified start / stop
    # ------------------------------------------------------------------ #

    def start_monitoring(self):
        self.start_observer()
        self.start_sysmon()
        self.start_presence()
        self.start_notif_monitor()

    def stop_monitoring(self):
        self.stop_observer()
        self.stop_sysmon()
        self.stop_presence()
        self.stop_notif_monitor()


_singleton: Optional[SystemMonitor] = None


def get_monitor() -> SystemMonitor:
    global _singleton
    if _singleton is None:
        _singleton = SystemMonitor()
    return _singleton


# ====================================================================== #
#  @register tools
# ====================================================================== #

# ---------------------------------------------------------------------- #
#  1. Unified tools
# ---------------------------------------------------------------------- #

@register(
    name="start_monitoring",
    description="Start all monitoring subsystems (window tracking, idle detection, clipboard, presence, notifications).",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
)
def start_monitoring() -> str:
    mon = get_monitor()
    mon.start_monitoring()
    return json.dumps({"success": True, "message": "All monitoring started"})


@register(
    name="stop_monitoring",
    description="Stop all monitoring subsystems.",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_monitoring() -> str:
    mon = get_monitor()
    mon.stop_monitoring()
    return json.dumps({"success": True, "message": "All monitoring stopped"})


@register(
    name="monitoring_status",
    description="Get status of all monitoring subsystems (observer, system monitor, presence, notifications).",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def monitoring_status() -> str:
    return get_monitor().monitoring_status()


# ---------------------------------------------------------------------- #
#  2. Observer compat
# ---------------------------------------------------------------------- #

@register(
    name="start_observer",
    description="Start monitoring active window and user activity.",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
)
def start_observer() -> str:
    get_monitor().start_observer()
    return json.dumps({"success": True, "message": "Observer started"})


@register(
    name="stop_observer",
    description="Stop monitoring active window and user activity.",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_observer() -> str:
    get_monitor().stop_observer()
    return json.dumps({"success": True, "message": "Observer stopped"})


@register(
    name="observer_status",
    description="Get observer status (running, idle, active app).",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def observer_status() -> str:
    return get_monitor().observer_status()


# ---------------------------------------------------------------------- #
#  3. System monitor compat
# ---------------------------------------------------------------------- #

@register(
    name="start_system_monitor",
    description="Iniciar monitoreo del sistema (ventana activa, portapapeles)",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
)
def start_system_monitor() -> str:
    get_monitor().start_sysmon()
    return json.dumps({"success": True, "message": "System monitor started"})


@register(
    name="stop_system_monitor",
    description="Detener monitoreo del sistema",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_system_monitor() -> str:
    get_monitor().stop_sysmon()
    return json.dumps({"success": True, "message": "System monitor stopped"})


@register(
    name="get_system_status",
    description="Obtener estado del monitor de sistema",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def get_system_status() -> str:
    s = get_monitor().get_system_status()
    return json.dumps({
        "success": True,
        "active_window": s["active_window"] or "N/A",
        "windows_seen": s["windows_seen"],
        "clips_seen": s["clips_seen"],
    })


# ---------------------------------------------------------------------- #
#  4. Presence tracker compat
# ---------------------------------------------------------------------- #

@register(
    name="start_presence_tracker",
    description="Iniciar detector de presencia/ausencia del usuario",
    parameters={
        "type": "object",
        "properties": {
            "away_threshold": {"type": "number", "description": "Segundos de inactividad para considerar ausente (default 120)"},
        },
        "required": [],
    },
    tier="premium",
)
def start_presence_tracker(away_threshold: float = 120.0) -> str:
    mon = get_monitor()
    mon._away_threshold = away_threshold
    mon.start_presence()
    return json.dumps({"success": True, "message": f"Presence tracker started (away after {away_threshold}s)"})


@register(
    name="stop_presence_tracker",
    description="Detener detector de presencia",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_presence_tracker() -> str:
    get_monitor().stop_presence()
    return json.dumps({"success": True, "message": "Presence tracker stopped"})


@register(
    name="presence_status",
    description="Estado del usuario: presente o ausente",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def presence_status() -> str:
    mon = get_monitor()
    s = mon.presence_status()
    return json.dumps({
        "success": True,
        "is_away": s["is_away"],
        "away_seconds": s["away_seconds"],
        "threshold": s["threshold"],
        "status": "AUSENTE" if s["is_away"] else "PRESENTE",
    })


# ---------------------------------------------------------------------- #
#  5. Notification monitor compat
# ---------------------------------------------------------------------- #

@register(
    name="start_notification_monitor",
    description="Iniciar monitoreo de notificaciones del sistema",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
)
def start_notification_monitor() -> str:
    get_monitor().start_notif_monitor()
    return json.dumps({"success": True, "message": "Notification monitor started"})


@register(
    name="stop_notification_monitor",
    description="Detener monitoreo de notificaciones",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
    internal=True,
)
def stop_notification_monitor() -> str:
    get_monitor().stop_notif_monitor()
    return json.dumps({"success": True, "message": "Notification monitor stopped"})


@register(
    name="get_notifications",
    description="Obtener notificaciones capturadas",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Maximo de notificaciones"},
        },
        "required": [],
    },
    tier="premium",
)
def get_notifications(limit: int = 10) -> str:
    mon = get_monitor()
    notifs = mon.get_notifications()
    if not notifs:
        return json.dumps({"success": True, "notifications": [], "message": "Sin notificaciones capturadas"})
    notifs = notifs[-limit:]
    return json.dumps({"success": True, "notifications": notifs, "count": len(notifs)})
