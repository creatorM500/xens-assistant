"""tools/tasks.py — Tareas en segundo plano (desacopladas del chat).

start_task lanza un loop LLM independiente que continúa el contexto de la
conversación actual sin bloquearla: el usuario puede seguir chateando
  mientras la tarea corre. Los pasos consumen Ainslup Credits normalmente
(uid heredado del contexto del orquestador).

Semántica: la tarea corre turnos (cada turno = un run_tool_loop). Si el
modelo responde una respuesta final sin tools, la tarea termina. Si agota
pasos a mitad de trabajo, espera más instrucciones (task_send) hasta un
idle timeout y luego se cierra sola.
"""
import asyncio, copy, json, logging

from .agents import AGENT_TOOLS as DEFAULT_TASK_TOOLS
from .registry import register
from ..core.tasks import task_manager

logger = logging.getLogger("xens.tools.tasks")

TASK_MAX_STEPS = 8          # pasos max. por turno
TASK_MAX_TURNS = 20         # turnos max. totales
TASK_IDLE_TIMEOUT = 180     # segundos esperando input antes de cerrarse
TASK_AGENT_SYSTEM = (
    "Eres un agente de tareas de Ainslup Assistant trabajando EN SEGUNDO PLANO "
    "sobre: {name}\n"
    "Continúa desde el contexto de la conversación. Trabaja de forma "
    "autónoma con las herramientas disponibles. Cuando completes la tarea, "
    "responde SOLO con un resumen final conciso (máximo 300 palabras)."
)


def _context() -> tuple[dict, list]:
    """(charge_ctx, session snapshot) del orquestador actual."""
    try:
        from ..core.llm import charge_ctx, session_ctx
        return (charge_ctx.get() or {}), (session_ctx.get() or [])
    except Exception:
        return {}, []


async def _run_turns(task_id: str, messages: list, tier: str, uid: str,
                     tools: set, name: str) -> str:
    """Ejecuta los turnos de la tarea hasta terminar o idle timeout."""
    from ..core.llm import run_tool_loop

    rec = task_manager.rec(task_id)
    inputs: asyncio.Queue = rec["_inputs"]
    progress_parts: list[str] = []
    turns = 0

    while turns < TASK_MAX_TURNS:
        if turns == 0:
            got_input = True
            while not inputs.empty():
                messages.append({"role": "user", "content": inputs.get_nowait()})
        else:
            try:
                text = await asyncio.wait_for(inputs.get(), timeout=TASK_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                break
            messages.append({"role": "user", "content": text})
            got_input = True

        if not got_input:
            continue

        turns += 1
        async for chunk in run_tool_loop(
            messages,
            max_iterations=TASK_MAX_STEPS,
            tier=tier,
            uid=uid,
            tool_names=tools,
            agent_name=name,
        ):
            if isinstance(chunk, dict) and chunk.get("type") == "content":
                progress_parts.append(chunk.get("content") or "")

        rec["progress"] = "".join(progress_parts)[-3000:]
        rec["_messages"] = messages

        last = messages[-1] if messages else {}
        if last.get("role") == "assistant" and not last.get("tool_calls"):
            break  # respuesta final del modelo: tarea completa

    result = rec.get("progress") or ""
    if not result:
        result = "(sin resultado)"
    return result


@register(name="start_task",
          description=(
              "Start a long-running background task that continues the current "
              "conversation autonomously without blocking the chat. Pro/Premium. "
              "Returns a task id; check task_status, send more input with task_send."
          ),
          tier="pro")
async def start_task(name: str, prompt: str, tools: list = None) -> str:
    if not name or not prompt:
        return json.dumps({"error": "name and prompt are required", "success": False})

    ctx, snapshot = _context()
    uid = ctx.get("uid")
    tier = ctx.get("tier") or "free"
    if not uid:
        return json.dumps({
            "error": "start_task requiere una cuenta autenticada (plan Pro o Premium).",
            "success": False,
        })
    if tier not in ("pro", "premium"):
        return json.dumps({
            "error": f"start_task requiere plan Pro o Premium (tu plan: {tier}).",
            "success": False,
            "required_tier": "pro",
        })
    if not snapshot:
        return json.dumps({"error": "No hay contexto de conversación para iniciar la tarea.", "success": False})

    messages = copy.deepcopy(snapshot)
    messages = [{"role": "system",
                 "content": TASK_AGENT_SYSTEM.format(name=name)}] + messages
    messages.append({"role": "user", "content": prompt})
    allowed = set(tools or []) | DEFAULT_TASK_TOOLS

    inputs = asyncio.Queue()
    task_id = task_manager.submit(
        name,
        lambda tid: _run_turns(tid, messages, tier, uid, allowed, name),
        meta={"uid": uid, "tier": tier, "prompt": prompt[:200]},
        attach={"_inputs": inputs},
    )
    return json.dumps({
        "success": True, "task_id": task_id, "name": name, "status": "running",
    }, ensure_ascii=False)


@register(name="task_status",
          description="Get the status, progress and result of a background task by id.",
          tier="free")
def task_status(task_id: str) -> str:
    rec = task_manager.status(task_id)
    if not rec:
        return json.dumps({"error": f"Task '{task_id}' not found", "success": False})
    return json.dumps({
        "success": True, "task_id": task_id, "name": rec["name"],
        "status": rec["status"], "progress": rec.get("progress"),
        "result": rec.get("result"), "error": rec.get("error"),
        "running_for": rec.get("running_for", 0),
    }, ensure_ascii=False)


@register(name="task_list",
          description="List background tasks (running and recent finished).",
          tier="free")
def task_list(limit: int = 10) -> str:
    return json.dumps({"success": True, "tasks": task_manager.list(limit)})


@register(name="task_send",
          description="Send more instructions to a RUNNING background task by id.",
          tier="free")
def task_send(task_id: str, text: str) -> str:
    if not text:
        return json.dumps({"error": "text is required", "success": False})
    rec = task_manager.rec(task_id)
    if not rec:
        return json.dumps({"error": f"Task '{task_id}' not found", "success": False})
    if rec["status"] not in ("queued", "running"):
        return json.dumps({
            "error": f"La tarea ya terminó (estado: {rec['status']}). Crea una nueva con start_task.",
            "success": False,
        })
    rec["_inputs"].put_nowait(text)
    return json.dumps({"success": True, "task_id": task_id, "status": "input_queued"})


@register(name="task_cancel",
          description="Cancel a queued or running background task by id.",
          tier="free")
def task_cancel(task_id: str) -> str:
    ok = task_manager.cancel(task_id)
    if not ok:
        rec = task_manager.status(task_id)
        status = rec["status"] if rec else "not_found"
        return json.dumps({"success": False, "task_id": task_id, "status": status})
    return json.dumps({"success": True, "task_id": task_id, "status": "cancelled"})