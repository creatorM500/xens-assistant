"""tools/triggers.py — Disparadores proactivos como herramientas.

create_trigger (Pro/Premium): agenda tareas automáticas (cada N minutos, a
una hora fija, o cuando termine otra tarea) que corren en segundo plano y
  consumen Ainslup Credits normalmente. list_triggers/delete_trigger gestionan
los disparadores del usuario.
"""
import json, logging

from .registry import register
from ..core.triggers import trigger_manager
from ..memory.session import Session

logger = logging.getLogger("xens.tools.triggers")

TRIGGER_AGENT_SYSTEM = (
    "Eres un agente de tareas automáticas de Ainslup Assistant ejecutando el "
    "disparador «{name}». Trabaja de forma autónoma con las herramientas "
    "disponibles, continúa desde el contexto de la conversación y responde "
    "SOLO con un resumen final conciso (máximo 300 palabras)."
)


def _context() -> tuple[dict, list]:
    try:
        from ..core.llm import charge_ctx
        return charge_ctx.get() or {}
    except Exception:
        return {}


async def _run_fired(task_id: str, trigger: dict) -> str:
    """Runner real de un disparo: loop LLM autónomo con el contexto del dueño."""
    from ..core.llm import run_tool_loop
    from ..core.tasks import task_manager

    name = trigger.get("name") or "tarea automática"
    owner = trigger.get("owner")
    tier = trigger.get("tier") or "free"
    prompt = trigger.get("prompt") or ""

    session = Session(f"acct:{owner}" if owner else "web")
    messages = [{"role": "system", "content": TRIGGER_AGENT_SYSTEM.format(name=name)}]
    for m in session.get_context(25):
        if isinstance(m, dict) and m.get("role") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})

    rec = task_manager.rec(task_id)
    parts = []
    try:
        async for chunk in run_tool_loop(
            messages, max_iterations=8, tier=tier, uid=owner,
            agent_name=name,
        ):
            if isinstance(chunk, dict) and chunk.get("type") == "content":
                parts.append(chunk.get("content") or "")
            elif isinstance(chunk, str):
                parts.append(chunk)
        result = "".join(parts)[-3000:] or "(sin resultado)"
        if rec is not None:
            rec["progress"] = result
            rec["result"] = result
        return result
    except Exception:
        logger.exception("Trigger task failed")
        raise


trigger_manager.runner = _run_fired


@register(name="create_trigger",
          description=(
              "Create an automatic trigger that runs a background task without "
              "being asked. schedule: {'every_minutes': N>=15}, {'at': 'HH:MM'} "
              "for a daily time, or {'on_task': 'done', 'task_name': '...'} to "
              "fire when a background task finishes. Pro/Premium. "
              "Manage with list_triggers / delete_trigger."
          ),
          tier="pro")
async def create_trigger(name: str, prompt: str, schedule: dict,
                         online_only: bool = False, daily_cap: int = 20) -> str:
    ctx = _context()
    uid = ctx.get("uid")
    tier = ctx.get("tier") or "free"
    if not uid:
        return json.dumps({
            "error": "create_trigger requiere una cuenta autenticada (plan Pro o Premium).",
            "success": False,
        })
    if tier not in ("pro", "premium"):
        return json.dumps({
            "error": f"create_trigger requiere plan Pro o Premium (tu plan: {tier}).",
            "success": False,
            "required_tier": "pro",
        })
    result = trigger_manager.create(
        name, schedule, prompt, owner=uid, tier=tier,
        online_only=online_only, daily_cap=daily_cap,
    )
    return json.dumps(result, ensure_ascii=False)


@register(name="list_triggers",
          description="List your automatic triggers (schedule, next fire, daily count).",
          tier="free")
def list_triggers() -> str:
    ctx = _context()
    uid = ctx.get("uid")
    triggers = trigger_manager.list(owner=uid)
    return json.dumps({"success": True, "triggers": triggers}, ensure_ascii=False)


@register(name="delete_trigger",
          description="Delete an automatic trigger by id.",
          tier="free")
def delete_trigger(trigger_id: str) -> str:
    ctx = _context()
    uid = ctx.get("uid")
    ok = trigger_manager.delete(trigger_id, owner=uid)
    if not ok:
        return json.dumps({
            "success": False, "trigger_id": trigger_id,
            "error": "Trigger no encontrado o sin permisos para eliminarlo.",
        })
    return json.dumps({"success": True, "trigger_id": trigger_id, "status": "deleted"})