"""Unit tests: TriggerManager (schedules, caps, online_only, on_task) + handlers.

Uso: python tests/test_triggers.py  (desde la raÃ­z del repo)
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.core import triggers as trig_mod
from ainslup_assistant.core.triggers import TriggerManager
from ainslup_assistant.core.llm import charge_ctx

FIRED = []


async def fake_runner(task_id, trigger):
    FIRED.append((task_id, trigger["name"]))
    await asyncio.sleep(0.05)
    return "ok " + trigger["name"]


async def main():
    # persistencia aislada en temp (nunca tocar el archivo real del usuario)
    tmp = Path(tempfile.mkdtemp(prefix="xens_triggers_test_"))
    trig_mod.TRIGGERS_FILE = tmp / "triggers.json"

    tm = TriggerManager()

    assert tm.validate_schedule({"every_minutes": 5}) is not None
    assert tm.validate_schedule({"every_minutes": 30}) is None
    assert tm.validate_schedule({"at": "25:00"}) is not None
    assert tm.validate_schedule({"at": "09:30"}) is None
    assert tm.validate_schedule({"on_task": "fail"}) is not None
    assert tm.validate_schedule({"on_task": "done", "task_name": "x"}) is None
    assert tm.validate_schedule({"foo": 1}) is not None
    assert tm.validate_schedule("nope") is not None

    r1 = tm.create("cada media hora", {"every_minutes": 30}, "revisa el clima",
                   owner="u-1", tier="pro")
    assert r1["success"], r1
    r2 = tm.create("a las 9", {"at": "09:00"}, "resumen diario", owner="u-1", tier="pro")
    assert r2["success"], r2
    assert tm.list(owner="u-2") == []
    assert len(tm.list(owner="u-1")) == 2
    assert tm.delete(r1["trigger_id"], owner="u-2") is False
    assert tm.delete(r1["trigger_id"], owner="u-1") is True
    tm2 = TriggerManager()
    assert len(tm2.list(owner="u-1")) == 1, tm2.list(owner="u-1")

    tm.runner = fake_runner
    tm2.runner = fake_runner
    events = []
    token = tm2.subscribe(lambda e: events.append(e))
    tr = tm2.get(r2["trigger_id"])
    tr["next_at"] = time.time() - 1
    tm2._tick()
    await asyncio.sleep(0.2)
    assert len(FIRED) == 1 and FIRED[0][1] == "a las 9", FIRED
    assert events[0]["status"] == "fired" and events[0]["name"] == "a las 9", events
    assert tr["fired_today"] == 1
    assert tr["next_at"] > time.time(), tr

    tr["fired_today"] = tr["daily_cap"]
    tr["next_at"] = time.time() - 1
    tm2._tick()
    await asyncio.sleep(0.1)
    assert len(FIRED) == 1, "no debe disparar con cap alcanzado"

    tm2.set_online_check(lambda uid: False)
    tr2 = tm2.create("online test", {"every_minutes": 15}, "p", owner="u-1", tier="pro",
                     online_only=True)
    tr2 = tm2.get(tr2["trigger_id"])
    tr2["next_at"] = time.time() - 1
    tm2._tick()
    await asyncio.sleep(0.1)
    assert len(FIRED) == 1, "online_only con dueÃ±o offline no debe disparar"
    tm2.set_online_check(lambda uid: True)
    tr2["next_at"] = time.time() - 1
    tm2._tick()
    await asyncio.sleep(0.1)
    assert len(FIRED) == 2, "con dueÃ±o online debe disparar"

    r3 = tm2.create("cuando termine", {"on_task": "done", "task_name": "compilar"},
                    "revisa el build", owner="u-1", tier="pro")
    tid3 = r3["trigger_id"]
    tm2._on_task_done({"status": "done", "name": "compilar", "meta": {"uid": "u-1"}})
    await asyncio.sleep(0.1)
    assert len(FIRED) == 3, FIRED
    assert tm2.get(tid3)["fired_today"] == 1
    tm2._on_task_done({"status": "done", "name": "compilar", "meta": {"uid": "u-1"}})
    await asyncio.sleep(0.1)
    assert len(FIRED) == 3, "cooldown debe bloquear el segundo disparo"
    tm2._on_task_done({"status": "done", "name": "otra", "meta": {"uid": "u-1"}})
    tm2._on_task_done({"status": "done", "name": "compilar", "meta": {"uid": "u-9"}})
    await asyncio.sleep(0.1)
    assert len(FIRED) == 3

    tm2.unsubscribe(token)

    # --- tools/triggers.py handlers con charge_ctx ---
    import ainslup_assistant.tools.triggers as ttrig

    charge_ctx.set(None)
    out = json.loads(await ttrig.create_trigger("x", "p", {"every_minutes": 30}))
    assert out["success"] is False and "cuenta" in out["error"], out

    charge_ctx.set({"uid": "u-free", "tier": "free"})
    out = json.loads(await ttrig.create_trigger("x", "p", {"every_minutes": 30}))
    assert out["success"] is False and "Pro" in out["error"], out

    charge_ctx.set({"uid": "u-1", "tier": "premium"})
    out = json.loads(await ttrig.create_trigger("premium test", "p", {"every_minutes": 15}))
    assert out["success"] is True and out["trigger_id"], out

    lst = json.loads(ttrig.list_triggers())
    assert lst["success"], lst
    assert any(t["id"] == out["trigger_id"] for t in lst["triggers"]), lst

    charge_ctx.set({"uid": "u-otro", "tier": "premium"})
    dl = json.loads(ttrig.delete_trigger(out["trigger_id"]))
    assert dl["success"] is False, dl
    charge_ctx.set({"uid": "u-1", "tier": "premium"})
    dl = json.loads(ttrig.delete_trigger(out["trigger_id"]))
    assert dl["success"] is True, dl

    print("UNIT_TRIGGERS_OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)


