"""Multiagente: el orquestador (run_tool_loop) puede lanzar sub-agentes
con spawn_agent. Cada sub-agente corre su propio loop LLM con un
subconjunto de herramientas, sesión aislada y descuento de créditos
normal (el uid viene del contexto de cobro del orquestador).

Acceso progresivo: Pro puede tener hasta 2 agentes concurrentes,
Premium hasta 4. Free no puede lanzar agentes (tool tier=pro).
"""
import asyncio, json, logging, threading, time

from .registry import register

logger = logging.getLogger("xens.agents")

# Subconjunto seguro por defecto: sin shell, sin uia, sin email, sin browser.
AGENT_TOOLS = {
    "read_file", "write_file", "list_dir", "grep_files", "diff_files",
    "web_search", "web_fetch",
    "wm_set", "wm_get", "wm_snapshot",
    "list_categories", "get_tool_schemas", "system_info",
}

MAX_CONCURRENT = {"free": 0, "pro": 2, "premium": 4}
MAX_AGENT_STEPS = 6

AGENT_SYSTEM = (
    "Eres un sub-agente de Xens Assistant ejecutando una tarea asignada por "
    "el orquestador. TAREA: {task}\n"
    "Usa las herramientas disponibles para completarla de la forma más "
    "eficiente posible. Cuando termines, responde SOLO con un resumen final "
    "conciso de los resultados y acciones tomadas (máximo 300 palabras), "
    "sin narrativa intermedia."
)

_lock = threading.Lock()
_agents: dict[str, dict] = {}
_counter = 0


def _new_id(name: str) -> str:
    global _counter
    _counter += 1
    return f"{name}-{int(time.time())}-{_counter}"


def _running_count() -> int:
    return sum(1 for a in _agents.values() if a["status"] == "running")


def _charge_context() -> dict:
    """uid/tier del orquestador actual (contextvar seteada por run_tool_loop)."""
    try:
        from ..core.llm import charge_ctx
        return charge_ctx.get() or {}
    except Exception:
        return {}


async def _run_agent(agent_id: str):
    rec = _agents[agent_id]
    ctx = _charge_context()
    uid = ctx.get("uid")
    tier = ctx.get("tier") or "free"
    try:
        from ..core.llm import run_tool_loop
        messages = [{"role": "system", "content": AGENT_SYSTEM.format(task=rec["task"])}]
        parts = []
        async for chunk in run_tool_loop(
            messages,
            max_iterations=MAX_AGENT_STEPS,
            tier=tier,
            uid=uid,
            tool_names=rec["tools"],
            agent_name=rec["name"],
        ):
            if isinstance(chunk, dict) and chunk.get("type") == "content":
                parts.append(chunk.get("content") or "")
        rec["result"] = "".join(parts).strip() or "(sin respuesta)"
        rec["status"] = "done"
    except asyncio.CancelledError:
        rec["status"] = "stopped"
        rec["result"] = "(detenido)"
    except Exception as e:
        logger.exception("Agent %s failed", agent_id)
        rec["status"] = "error"
        rec["error"] = str(e)
    finally:
        rec["finished_at"] = time.time()


@register(name="spawn_agent",
          description=(
              "Launch a sub-agent to complete a task autonomously with its own "
              "tool loop (multi-agent). Pro: up to 2 concurrent, Premium: 4. "
              "Returns the agent id; check progress with agent_status."
          ),
          tier="pro")
async def spawn_agent(name: str, task: str, tools: list = None) -> str:
    if not name or not task:
        return json.dumps({"error": "name and task are required", "success": False})
    from ..tools.registry import registry
    tier = registry.get_tier()
    max_conc = MAX_CONCURRENT.get(tier, 0)
    with _lock:
        running = _running_count()
        if max_conc <= 0:
            return json.dumps({
                "error": f"spawn_agent requires {tier} tier with agent access",
                "success": False, "required_tier": "pro",
            })
        if running >= max_conc:
            return json.dumps({
                "error": f"Límite de agentes concurrentes alcanzado ({running}/{max_conc} para {tier}). Espera a que termine uno.",
                "success": False, "running": running, "max": max_conc,
            })
        allowed_tools = set(tools or []) | AGENT_TOOLS
        agent_id = _new_id(name)
        _agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "task": task,
            "tools": sorted(allowed_tools),
            "status": "running",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tier": tier,
        }
        task_handle = asyncio.ensure_future(_run_agent(agent_id))
        _agents[agent_id]["_task"] = task_handle
    return json.dumps({
        "success": True, "agent_id": agent_id, "status": "running",
        "concurrent": _running_count(), "max": max_conc,
    })


@register(name="agent_status", description="Get the status and result of a sub-agent by id.", tier="free")
def agent_status(agent_id: str) -> str:
    rec = _agents.get(agent_id)
    if not rec:
        return json.dumps({"error": f"Agent '{agent_id}' not found", "success": False})
    return json.dumps({
        "success": True, "agent_id": agent_id, "name": rec["name"],
        "status": rec["status"], "result": rec.get("result"),
        "error": rec.get("error"), "running_for": int(time.time() - rec["started_at"]),
    }, ensure_ascii=False)


@register(name="list_agents", description="List sub-agents (running and recent finished).", tier="free")
def list_agents(limit: int = 10) -> str:
    recent = sorted(_agents.values(), key=lambda a: a["started_at"], reverse=True)[:limit]
    return json.dumps({
        "success": True,
        "running": _running_count(),
        "agents": [
            {"agent_id": a["id"], "name": a["name"], "status": a["status"],
             "started_at": int(a["started_at"])}
            for a in recent
        ],
    })


@register(name="agent_stop", description="Stop a running sub-agent by id.", tier="free")
async def agent_stop(agent_id: str) -> str:
    rec = _agents.get(agent_id)
    if not rec:
        return json.dumps({"error": f"Agent '{agent_id}' not found", "success": False})
    if rec["status"] == "running":
        task = rec.get("_task")
        if task:
            task.cancel()
        rec["status"] = "stopping"
        return json.dumps({"success": True, "agent_id": agent_id, "status": "stopping"})
    return json.dumps({"success": True, "agent_id": agent_id, "status": rec["status"]})