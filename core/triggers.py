"""core/triggers.py — Disparadores proactivos (scheduled y por eventos).

Un disparador lanza una tarea en segundo plano de forma automática:

- schedule {"every_minutes": N} : cada N minutos (mínimo 15).
- schedule {"at": "HH:MM"}     : una vez por día a la hora indicada.
- schedule {"on_task": "done", "task_name": "..."} : cuando termina una
  tarea en segundo plano (task_name opcional).

El disparo reusa el TaskManager: corre un loop LLM autónomo (tools/triggers
  provee el runner) que consume Ainslup Credits normalmente según el dueño.

Control de costos:
- online_only: solo dispara si el dueño está conectado (WS activo).
- daily_cap: máximo de disparos por día por disparador (20 por defecto).
- El runner corre con el tier/uid del dueño -> el gate de créditos aplica.
"""
import asyncio, json, logging, time, uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("xens.triggers")

TRIGGERS_FILE = Path.home() / ".ainslup" / "triggers.json"
TICK_SECONDS = 30
DEFAULT_DAILY_CAP = 20
MIN_EVERY_MINUTES = 15
MAX_EVERY_MINUTES = 24 * 60
ON_TASK_COOLDOWN = 60  # segundos entre disparos on_task del mismo disparador


class TriggerManager:
    def __init__(self):
        self._triggers: list[dict] = []
        self._listeners: dict[int, Callable] = {}
        self._next_listener_id = 1
        # Runner para ejecutar el disparo: lo registra tools/triggers al
        # importarse (evita dependencia circular core -> tools).
        self.runner: Optional[Callable] = None
        self._online_check: Optional[Callable] = None
        self._ticker: Optional[asyncio.Task] = None
        self._task_token: Optional[int] = None
        self._load()

    # ---------------- eventos ----------------

    def subscribe(self, fn: Callable) -> int:
        token = self._next_listener_id
        self._next_listener_id += 1
        self._listeners[token] = fn
        return token

    def unsubscribe(self, token: int):
        self._listeners.pop(token, None)

    def _emit(self, event: dict):
        for fn in list(self._listeners.values()):
            try:
                result = fn(dict(event))
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                logger.exception("Trigger listener error")

    # ---------------- persistencia ----------------

    def _load(self):
        if TRIGGERS_FILE.exists():
            try:
                with open(TRIGGERS_FILE, encoding="utf-8") as f:
                    self._triggers = json.load(f).get("triggers", [])
            except Exception:
                logger.exception("Failed to load triggers")
                self._triggers = []

    def _save(self):
        try:
            TRIGGERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TRIGGERS_FILE, "w", encoding="utf-8") as f:
                json.dump({"triggers": self._triggers}, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save triggers")

    # ---------------- API ----------------

    @staticmethod
    def validate_schedule(schedule) -> Optional[str]:
        """Devuelve un error si el schedule no es válido, None si lo es."""
        if not isinstance(schedule, dict):
            return "schedule must be an object"
        if "every_minutes" in schedule:
            n = schedule["every_minutes"]
            if not isinstance(n, int) or isinstance(n, bool):
                return "every_minutes must be an integer"
            if n < MIN_EVERY_MINUTES or n > MAX_EVERY_MINUTES:
                return f"every_minutes must be between {MIN_EVERY_MINUTES} and {MAX_EVERY_MINUTES}"
            return None
        if "at" in schedule:
            at = schedule["at"]
            if not isinstance(at, str) or len(at) != 5 or at[2] != ":":
                return "at must be 'HH:MM'"
            hh, mm = at.split(":")
            if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                return "at must be a valid 'HH:MM' time"
            return None
        if "on_task" in schedule:
            if schedule["on_task"] != "done":
                return "on_task only supports 'done'"
            tn = schedule.get("task_name")
            if tn is not None and not isinstance(tn, str):
                return "task_name must be a string"
            return None
        return "schedule must contain every_minutes, at or on_task"

    def _next_at(self, schedule: dict, last_fired_at=None) -> Optional[float]:
        now = time.time()
        if "every_minutes" in schedule:
            base = last_fired_at or now
            return base + schedule["every_minutes"] * 60
        if "at" in schedule:
            hh, mm = (int(x) for x in schedule["at"].split(":"))
            today = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
            at_ts = today.timestamp()
            if at_ts <= now + 1:
                from datetime import timedelta
                at_ts = (today + timedelta(days=1)).timestamp()
            return at_ts
        return None  # on_task: sin agenda

    def create(self, name: str, schedule: dict, prompt: str,
               owner: Optional[str] = None, tier: str = "free",
               online_only: bool = False, daily_cap: int = DEFAULT_DAILY_CAP) -> dict:
        name = (name or "").strip()
        prompt = (prompt or "").strip()
        if not name:
            return {"error": "name is required", "success": False}
        if not prompt:
            return {"error": "prompt is required", "success": False}
        err = self.validate_schedule(schedule)
        if err:
            return {"error": err, "success": False}
        if daily_cap is None or int(daily_cap) < 1:
            daily_cap = DEFAULT_DAILY_CAP

        today = datetime.now().strftime("%Y-%m-%d")
        trigger = {
            "id": "tr-" + uuid.uuid4().hex[:12],
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "owner": owner,
            "tier": tier,
            "online_only": bool(online_only),
            "daily_cap": int(daily_cap),
            "fired_today": 0,
            "day_key": today,
            "last_fired_at": None,
            "next_at": self._next_at(schedule),
            "created_at": time.time(),
        }
        self._triggers.append(trigger)
        self._save()
        return {"success": True, "trigger_id": trigger["id"], "name": name,
                "schedule": schedule}

    def delete(self, trigger_id: str, owner: Optional[str] = None) -> bool:
        for i, t in enumerate(self._triggers):
            if t["id"] == trigger_id:
                if t.get("owner") != owner:
                    return False
                self._triggers.pop(i)
                self._save()
                return True
        return False

    def list(self, owner: Optional[str] = None) -> list[dict]:
        result = []
        for t in self._triggers:
            if t.get("owner") == owner:
                result.append({
                    "id": t["id"],
                    "name": t["name"],
                    "schedule": t["schedule"],
                    "online_only": t.get("online_only", False),
                    "fired_today": t.get("fired_today", 0),
                    "daily_cap": t.get("daily_cap", DEFAULT_DAILY_CAP),
                    "last_fired_at": t.get("last_fired_at"),
                    "next_at": t.get("next_at"),
                    "created_at": t.get("created_at"),
                })
        return result

    def get(self, trigger_id: str) -> Optional[dict]:
        for t in self._triggers:
            if t["id"] == trigger_id:
                return t
        return None

    # ---------------- ejecución ----------------

    def _is_online(self, owner: Optional[str]) -> bool:
        if not owner:
            return True  # modo local: siempre "conectado"
        if self._online_check is None:
            return True
        try:
            return bool(self._online_check(owner))
        except Exception:
            return True

    def _can_fire(self, t: dict, now: float) -> bool:
        if t.get("online_only") and not self._is_online(t.get("owner")):
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        if t.get("day_key") != today:
            t["day_key"] = today
            t["fired_today"] = 0
        return (t.get("fired_today", 0) < t.get("daily_cap", DEFAULT_DAILY_CAP))

    def _fire(self, t: dict):
        now = time.time()
        if not self._can_fire(t, now):
            return
        if self.runner is None:
            logger.error("Trigger runner not registered (tools.triggers not imported)")
            self._emit({"id": t["id"], "name": t["name"], "status": "error",
                        "reason": "runner_not_available"})
            return
        task_id = None
        try:
            owner = t.get("owner")
            tier = t.get("tier") or "free"
            task_id = task_manager.submit(
                t["name"],
                lambda tid, tr=t: self._run_fired(tid, tr),
                meta={"uid": owner, "kind": "trigger", "trigger_id": t["id"]},
            )
            t["fired_today"] = t.get("fired_today", 0) + 1
            t["last_fired_at"] = now
            if "on_task" not in t.get("schedule", {}):
                t["next_at"] = self._next_at(t["schedule"], now)
            self._save()
            self._emit({"id": t["id"], "name": t["name"], "status": "fired",
                        "task_id": task_id})
        except Exception:
            logger.exception("Trigger fire failed")
            self._emit({"id": t["id"], "name": t["name"], "status": "error",
                        "reason": "fire_failed"})

    async def _run_fired(self, task_id: str, trigger: dict):
        """Runner por defecto: lo sustituye tools/triggers al importarse."""
        if self.runner:
            return await self.runner(task_id, trigger)
        return "(sin runner)"

    def _tick(self):
        now = time.time()
        for t in self._triggers:
            sch = t.get("schedule") or {}
            if "on_task" in sch:
                continue  # eventos, no horarios
            next_at = t.get("next_at")
            if next_at is None:
                t["next_at"] = self._next_at(sch, t.get("last_fired_at"))
                self._save()
                continue
            if now >= next_at:
                self._fire(t)

    def _on_task_done(self, rec: dict):
        """Hook del TaskManager: dispara schedules on_task."""
        if rec.get("status") != "done":
            return
        for t in self._triggers:
            sch = t.get("schedule") or {}
            if sch.get("on_task") != "done":
                continue
            task_name = sch.get("task_name")
            if task_name and task_name != rec.get("name"):
                continue
            owner = t.get("owner")
            rec_owner = (rec.get("meta") or {}).get("uid")
            if owner != rec_owner:
                continue
            now = time.time()
            last = t.get("last_fired_at")
            if last is not None and now - last < ON_TASK_COOLDOWN:
                continue
            self._fire(t)

    # ---------------- ciclo de vida ----------------

    def start(self):
        if self._ticker is None:
            self._ticker = asyncio.ensure_future(self._tick_loop())
            self._task_token = task_manager.subscribe(self._on_task_done)

    async def _tick_loop(self):
        try:
            while True:
                await asyncio.sleep(TICK_SECONDS)
                try:
                    self._tick()
                except Exception:
                    logger.exception("Trigger tick error")
        except asyncio.CancelledError:
            pass

    def stop(self):
        if self._ticker is not None:
            self._ticker.cancel()
            self._ticker = None
        if self._task_token is not None:
            task_manager.unsubscribe(self._task_token)
            self._task_token = None

    def set_online_check(self, fn: Optional[Callable]):
        self._online_check = fn


from .tasks import task_manager  # noqa: E402  (evita ciclo con tools)

trigger_manager = TriggerManager()