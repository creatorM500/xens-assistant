"""tasks.py — Gestor de tareas en segundo plano.

Desacopla el canal conversacional de la ejecución: el orquestador puede
delegar trabajo largo a una tarea background (tool start_task) que corre su
propio loop LLM sin bloquear el chat. Los eventos de estado se emiten a los
suscriptores (p.ej. las conexiones WS, para el evento task_event).
"""
import asyncio, logging, threading, time, uuid
from typing import Callable, Optional

logger = logging.getLogger("xens.tasks")


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._listeners: dict[int, Callable] = {}
        self._listener_id = 0

    # ── suscripción de eventos ──────────────────────────────────
    def subscribe(self, callback: Callable) -> int:
        """callback(dict) — recibe una copia del registro al terminar
        (done/error/cancelled). Puede ser síncrono o coroutine."""
        with self._lock:
            self._listener_id += 1
            self._listeners[self._listener_id] = callback
            return self._listener_id

    def unsubscribe(self, listener_id: int):
        with self._lock:
            self._listeners.pop(listener_id, None)

    def _emit(self, rec: dict):
        with self._lock:
            listeners = list(self._listeners.values())
        for cb in listeners:
            try:
                result = cb(dict(rec))
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                logger.exception("Task listener error")

    # ── ciclo de vida ───────────────────────────────────────────
    def submit(self, name: str, coro_factory: Callable, meta: dict = None,
               attach: dict = None) -> str:
        """coro_factory: async callable(task_id) -> result (se llama dentro del loop).
        attach: campos extra del registro (p.ej. colas de entrada)."""
        task_id = f"t{int(time.time())}-{uuid.uuid4().hex[:6]}"
        rec: dict = {
            "id": task_id,
            "name": name,
            "meta": meta or {},
            "status": "queued",
            "result": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
        rec.update(attach or {})
        with self._lock:
            self._tasks[task_id] = rec
        handle = asyncio.ensure_future(self._run(task_id, coro_factory))
        rec["_handle"] = handle
        return task_id

    async def _run(self, task_id: str, coro_factory: Callable):
        rec = self._tasks.get(task_id)
        if not rec:
            return
        rec["started_at"] = time.time()
        rec["status"] = "running"
        try:
            result = await coro_factory(task_id)
            rec["result"] = result
            rec["status"] = "done"
        except asyncio.CancelledError:
            rec["status"] = "cancelled"
        except Exception as e:
            logger.exception("Task %s failed", task_id)
            rec["error"] = str(e)
            rec["status"] = "error"
        finally:
            rec["finished_at"] = time.time()
            self._emit(rec)

    def cancel(self, task_id: str) -> bool:
        rec = self._tasks.get(task_id)
        if not rec:
            return False
        if rec["status"] in ("queued", "running"):
            handle = rec.get("_handle")
            if handle:
                handle.cancel()
            rec["status"] = "cancelled"
            rec["finished_at"] = time.time()
            self._emit(rec)
            return True
        return False

    # ── consultas ───────────────────────────────────────────────
    def rec(self, task_id: str) -> Optional[dict]:
        """Registro RAW (mutable, con colas adjuntas). Uso interno de tools."""
        return self._tasks.get(task_id)

    def status(self, task_id: str) -> Optional[dict]:
        rec = self._tasks.get(task_id)
        if not rec:
            return None
        out = dict(rec)
        out["running_for"] = (
            int(time.time() - rec["started_at"]) if rec["started_at"] else 0
        )
        return out

    def list(self, limit: int = 10) -> list[dict]:
        recent = sorted(
            self._tasks.values(),
            key=lambda t: t["started_at"] or 0,
            reverse=True,
        )[:limit]
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "started_at": int(r["started_at"]) if r["started_at"] else None,
                "meta": r.get("meta") or {},
            }
            for r in recent
        ]


task_manager = TaskManager()