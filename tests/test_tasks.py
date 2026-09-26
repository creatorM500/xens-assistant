"""Unit tests: TaskManager + handlers de tasks (snapshot de contexto, eventos).

Uso: python tests/test_tasks.py  (desde la raÃ­z del repo)
"""
import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.core.tasks import task_manager
from ainslup_assistant.core.llm import charge_ctx, session_ctx
import ainslup_assistant.tools.tasks as tt
from ainslup_assistant.core import llm as core_llm

RESULTS = []


async def sleep_ok(task_id):
    await asyncio.sleep(0.3)
    return "ok"


async def sleep_fail(task_id):
    await asyncio.sleep(0.2)
    raise RuntimeError("boom")


async def main():
    # --- TaskManager unit ---
    events = []
    token = task_manager.subscribe(lambda e: events.append(e))

    t1 = task_manager.submit("tarea_a", sleep_ok, {"uid": "u1", "name": "tarea_a"})
    st = task_manager.status(t1)
    assert st["status"] in ("queued", "running", "done"), st
    assert st["meta"]["uid"] == "u1"

    t2 = task_manager.submit("tarea_b", sleep_fail, {"uid": "u2", "name": "tarea_b"})
    t3 = task_manager.submit("tarea_c", lambda tid: asyncio.sleep(60), {"uid": "u1", "name": "tarea_c"})
    task_manager.cancel(t3)
    assert task_manager.status(t3)["status"] == "cancelled"

    await asyncio.sleep(0.8)
    assert task_manager.status(t1)["status"] == "done"
    assert task_manager.status(t1)["result"] == "ok"
    assert "boom" in task_manager.status(t2).get("error", "")

    done = [e for e in events if e.get("status") == "done"]
    err = [e for e in events if e.get("status") == "error"]
    canc = [e for e in events if e.get("status") == "cancelled"]
    assert len(done) == 1 and done[0]["id"] == t1, done
    assert len(err) == 1 and err[0]["id"] == t2, err
    assert len(canc) == 1 and canc[0]["id"] == t3, canc
    assert done[0]["meta"]["uid"] == "u1"
    task_manager.unsubscribe(token)

    # --- tools/tasks.py handlers con run_tool_loop falso ---
    calls = {"n": 0, "messages": None}

    async def fake_run(messages, max_iterations=5, tier="free", uid=None,
                       charge=True, tool_names=None, agent_name=None):
        calls["n"] += 1
        calls["messages"] = messages
        messages.append({"role": "assistant", "content": "RESULTADO_FINAL_DE_PRUEBA"})
        yield {"type": "content", "content": "RESULTADO_FINAL_DE_PRUEBA"}

    core_llm.run_tool_loop = fake_run
    tt_tokens = task_manager.subscribe(lambda e: RESULTS.append(("evt", e)))

    charge_ctx.set({"uid": "u_test", "tier": "premium"})
    session_ctx.set([{"role": "user", "content": "historico"}] + [{"role": "user", "content": "haz algo"}])

    out = json.loads(await tt.start_task("lanzar una tarea de prueba", "calcula algo"))
    assert out["success"] is True, out
    tid = out["task_id"]

    async def wait_done():
        s = None
        for _ in range(50):
            s = json.loads(tt.task_status(tid))
            if s["status"] in ("done", "error", "cancelled"):
                return s
            await asyncio.sleep(0.1)
        return s

    s = await wait_done()
    assert calls["n"] >= 1, "la tarea debiÃ³ ejecutar turnos"
    assert s["status"] == "done", s
    assert "RESULTADO_FINAL" in s.get("progress", ""), s

    lst = json.loads(tt.task_list())
    assert any(x["id"] == tid and x["status"] == "done" for x in lst["tasks"]), lst

    out2 = json.loads(await tt.start_task("otra tarea lenta", "haz algo"))
    tid2 = out2["task_id"]
    c = json.loads(tt.task_cancel(tid2))
    assert c["success"] is True, c

    # tareas sin credenciales (local) -> rechazadas
    charge_ctx.set(None)
    session_ctx.set(None)
    out3 = json.loads(await tt.start_task("tarea local", "haz algo"))
    assert out3["success"] is False, out3

    task_manager.unsubscribe(tt_tokens)
    print("UNIT_TASKS_OK", json.dumps({"tasks": len(task_manager.list()),
                                       "evt_count": len(RESULTS)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)


