from .registry import register
"""
goals.py — Goal system: create, track, prioritize, and complete goals.
Persistent JSON storage in ~/.xens/goals.json.
Ported from Omni goal_system.py with cleanup and JSON returns.
"""
import json, logging, threading, time, uuid
from pathlib import Path

logger = logging.getLogger("xens.tools.goals")

_GOALS_PATH = Path.home() / ".xens" / "goals.json"
_LOCK = threading.Lock()


def _load() -> dict:
    with _LOCK:
        if not _GOALS_PATH.exists():
            return {"goals": []}
        try:
            return json.loads(_GOALS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"goals": []}


def _save(data: dict):
    _GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        try:
            _GOALS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


@register(name="goal_create", description="Create a new goal with optional steps.", tier="free")
def goal_create(title: str, description: str = "", priority: int = 1,
                category: str = "general", steps: list[str] = None) -> str:
    if priority < 1:
        priority = 1
    if priority > 5:
        priority = 5
    goal_id = uuid.uuid4().hex[:12]
    data = _load()
    data["goals"].append({
        "id": goal_id,
        "title": title,
        "description": description,
        "priority": priority,
        "category": category,
        "status": "active",
        "progress": 0.0,
        "steps": [{"text": p, "completed": False} for p in (steps or [])],
        "created": time.time(),
        "updated": time.time(),
        "completed_at": None,
    })
    _save(data)
    return json.dumps({"success": True, "goal_id": goal_id, "title": title})


@register(name="goal_list", description="List goals with optional status/category filter.", tier="free")
def goal_list(status: str = None, category: str = None, limit: int = 20) -> str:
    data = _load()
    goals = list(data["goals"])
    if status:
        goals = [g for g in goals if g.get("status") == status]
    if category:
        goals = [g for g in goals if g.get("category") == category]
    goals.sort(key=lambda g: (-g.get("priority", 1), -g.get("created", 0)))
    goals = goals[:limit]
    for g in goals:
        g["created_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(g.get("created", 0)))
        g["updated_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(g.get("updated", 0)))
        if g.get("completed_at"):
            g["completed_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(g["completed_at"]))
    return json.dumps({"success": True, "count": len(goals), "goals": goals})


@register(name="goal_update_progress", description="Update goal progress (0.0 to 1.0).", tier="free")
def goal_update_progress(goal_id: str, progress: float) -> str:
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id:
            g["progress"] = max(0.0, min(1.0, progress))
            g["updated"] = time.time()
            if progress >= 1.0:
                g["status"] = "completed"
                g["completed_at"] = time.time()
            _save(data)
            return json.dumps({"success": True, "goal_id": goal_id, "progress": progress})
    return json.dumps({"error": f"Goal not found: {goal_id}", "success": False})


@register(name="goal_complete_step", description="Mark a goal step as completed.", tier="free")
def goal_complete_step(goal_id: str, step_index: int) -> str:
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id:
            steps = g.get("steps", [])
            if 0 <= step_index < len(steps):
                steps[step_index]["completed"] = True
                completed = sum(1 for p in steps if p["completed"])
                g["progress"] = completed / len(steps) if steps else 1.0
                g["updated"] = time.time()
                if g["progress"] >= 1.0:
                    g["status"] = "completed"
                    g["completed_at"] = time.time()
                _save(data)
                return json.dumps({"success": True, "goal_id": goal_id, "progress": g["progress"]})
            return json.dumps({"error": f"Step index {step_index} out of range (0-{len(steps)-1})", "success": False})
    return json.dumps({"error": f"Goal not found: {goal_id}", "success": False})


@register(name="goal_pause", description="Pause an active goal.", tier="free")
def goal_pause(goal_id: str) -> str:
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id and g["status"] == "active":
            g["status"] = "paused"
            g["updated"] = time.time()
            _save(data)
            return json.dumps({"success": True, "goal_id": goal_id, "status": "paused"})
    return json.dumps({"error": f"Goal not found or not active: {goal_id}", "success": False})


@register(name="goal_resume", description="Resume a paused goal.", tier="free")
def goal_resume(goal_id: str) -> str:
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id and g["status"] == "paused":
            g["status"] = "active"
            g["updated"] = time.time()
            _save(data)
            return json.dumps({"success": True, "goal_id": goal_id, "status": "active"})
    return json.dumps({"error": f"Goal not found or not paused: {goal_id}", "success": False})


@register(name="goal_cancel", description="Cancel an active or paused goal.", tier="free")
def goal_cancel(goal_id: str) -> str:
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id and g["status"] in ("active", "paused"):
            g["status"] = "cancelled"
            g["updated"] = time.time()
            _save(data)
            return json.dumps({"success": True, "goal_id": goal_id, "status": "cancelled"})
    return json.dumps({"error": f"Goal not found: {goal_id}", "success": False})


@register(name="goal_stats", description="Get goal statistics (total, active, completed, etc.).", tier="free")
def goal_stats() -> str:
    data = _load()
    total = len(data["goals"])
    active = sum(1 for g in data["goals"] if g.get("status") == "active")
    completed = sum(1 for g in data["goals"] if g.get("status") == "completed")
    paused = sum(1 for g in data["goals"] if g.get("status") == "paused")
    avg_progress = round(sum(g.get("progress", 0) for g in data["goals"]) / max(total, 1), 3)
    return json.dumps({
        "success": True, "total": total, "active": active,
        "completed": completed, "paused": paused,
        "avg_progress": avg_progress,
    })
