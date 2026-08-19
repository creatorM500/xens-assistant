import json
import os
import re
import threading
import time
from datetime import datetime
from .registry import register
from ..core.llm import charge_ctx

STORAGE_DIR = os.path.join(os.path.expanduser("~"), ".xens")
STORAGE_PATH = os.path.join(STORAGE_DIR, "user_profile.json")
_file_lock = threading.Lock()


def _storage_path() -> str:
    # Perfil aislado por cuenta (SaaS): ~/.xens/user_profile-{uid}.json.
    ctx = charge_ctx.get()
    uid = (ctx or {}).get("uid") if isinstance(ctx, dict) else None
    if uid:
        return os.path.join(STORAGE_DIR, f"user_profile-{uid}.json")
    return STORAGE_PATH

CONFIDENCE_DECAY_DAYS = 14
CONFIDENCE_BOOST = 0.1
CONFIDENCE_INITIAL = 0.5
CONFIDENCE_MAX = 1.0
CONFIDENCE_MIN = 0.1

_SENSITIVE = ["contraseña", "password", "clave", "tarjeta", "numero de",
              "credenciales", "token", "secret", "pin", "cvv", "seguridad",
              "credit card", "ssn", "dni", "passport"]

_PATTERNS = [
    (r"(?:me\s+llamo|mi\s+nombre\s+es|llámame)\s+(.+)", "nombre"),
    (r"(?:trabajo\s+(?:en|como|de)\s+|soy\s+)(.+)", "trabajo"),
    (r"(?:vivo\s+en|resido\s+en|mi\s+dirección\s+es)\s+(.+)", "ubicacion"),
    (r"tengo\s+(\d+)\s*(?:años|años)", "edad"),
    (r"(?:me\s+gusta|gusta)\s+(.+)", "gustos"),
    (r"(?:no\s+me\s+gusta|odio|detesto)\s+(.+)", "disgustos"),
    (r"(?:soy|suelo\s+ser)\s+(.+)", "descripcion"),
    (r"(?:mi\s+(.+?)\s+es\s+(.+))", None),
]


def _empty() -> dict:
    return {
        "profile": {},
        "preferences": {},
        "corrections": [],
        "facts": [],
        "cognitive_facts": {},
        "snippets": [],
    }


def _load() -> dict:
    path = _storage_path()
    with _file_lock:
        if not os.path.exists(path):
            return _empty()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return _empty()


def _save(data: dict):
    path = _storage_path()
    with _file_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _make_cognitive_entry(value: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "value": value,
        "confidence": CONFIDENCE_INITIAL,
        "times_mentioned": 1,
        "first_seen": now,
        "last_updated": now,
    }


def _apply_decay(entry: dict):
    if not isinstance(entry, dict):
        return
    try:
        updated = datetime.fromisoformat(entry.get("last_updated", ""))
        days = (datetime.now() - updated).days
        if days > 0:
            decay = days * (CONFIDENCE_BOOST / CONFIDENCE_DECAY_DAYS)
            entry["confidence"] = max(CONFIDENCE_MIN, entry.get("confidence", CONFIDENCE_INITIAL) - decay)
    except Exception:
        pass


def _reinforce_cognitive(key: str, value: str, data: dict):
    cog = data.setdefault("cognitive_facts", {})
    existing = cog.get(key)
    if isinstance(existing, dict):
        existing["value"] = value
        existing["confidence"] = min(CONFIDENCE_MAX, existing.get("confidence", CONFIDENCE_INITIAL) + CONFIDENCE_BOOST)
        existing["times_mentioned"] = existing.get("times_mentioned", 0) + 1
        existing["last_updated"] = datetime.now().isoformat()
    else:
        cog[key] = _make_cognitive_entry(value)


def _run_decay(data: dict):
    now = datetime.now()
    cog = data.get("cognitive_facts", {})
    for key in list(cog.keys()):
        entry = cog[key]
        if not isinstance(entry, dict):
            continue
        _apply_decay(entry)
        if entry["confidence"] <= CONFIDENCE_MIN:
            try:
                last = datetime.fromisoformat(entry.get("last_updated", ""))
                if (now - last).days > 30:
                    del cog[key]
            except Exception:
                pass

# ── aprender_* (aprendizaje.py) ──────────────────────────────────────────


@register(
    name="aprender_recordar",
    description="Recordar informacion personal del usuario (nombre, gustos, etc.)",
    parameters={
        "type": "object",
        "properties": {
            "clave": {"type": "string", "description": "Categoria (nombre, trabajo, gustos, etc)"},
            "valor": {"type": "string", "description": "Valor a recordar"},
        },
        "required": ["clave", "valor"],
    },
    tier="free",
)
def aprender_recordar(clave: str, valor: str) -> str:
    data = _load()
    data.setdefault("profile", {})[clave] = {
        "valor": valor,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _reinforce_cognitive(clave, valor, data)
    _save(data)
    return json.dumps({"success": True, "message": f"Recordado: {clave} = {valor}"})


@register(
    name="aprender_preferencia",
    description="Guardar una preferencia del usuario",
    parameters={
        "type": "object",
        "properties": {
            "categoria": {"type": "string", "description": "Categoria"},
            "valor": {"type": "string", "description": "Valor de preferencia"},
        },
        "required": ["categoria", "valor"],
    },
    tier="free",
)
def aprender_preferencia(categoria: str, valor: str) -> str:
    data = _load()
    data.setdefault("preferences", {}).setdefault(categoria, [])
    if valor not in data["preferences"][categoria]:
        data["preferences"][categoria].append(valor)
    _save(data)
    return json.dumps({"success": True, "message": f"Preferencia guardada: {categoria} -> {valor}"})


@register(
    name="aprender_correccion",
    description="Guardar una correccion del usuario para mejorar respuestas",
    parameters={
        "type": "object",
        "properties": {
            "error": {"type": "string", "description": "Lo que se dijo incorrectamente"},
            "correcto": {"type": "string", "description": "La version correcta"},
        },
        "required": ["error", "correcto"],
    },
    tier="free",
)
def aprender_correccion(error: str, correcto: str) -> str:
    data = _load()
    data.setdefault("corrections", []).append({
        "error": error,
        "correcto": correcto,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if len(data["corrections"]) > 50:
        data["corrections"] = data["corrections"][-50:]
    _save(data)
    return json.dumps({"success": True, "message": "Correccion guardada"})


@register(
    name="aprender_hecho",
    description="Guardar un hecho relevante sobre el usuario o entorno",
    parameters={
        "type": "object",
        "properties": {
            "hecho": {"type": "string", "description": "Hecho a guardar"},
        },
        "required": ["hecho"],
    },
    tier="free",
)
def aprender_hecho(hecho: str) -> str:
    data = _load()
    data.setdefault("facts", []).append({
        "hecho": hecho,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if len(data["facts"]) > 100:
        data["facts"] = data["facts"][-100:]
    _save(data)
    return json.dumps({"success": True, "message": "Hecho guardado"})


@register(
    name="aprender_contexto",
    description="Obtener todo el contexto personal aprendido sobre el usuario",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def aprender_contexto() -> str:
    data = _load()
    _run_decay(data)
    lines = []
    if data.get("profile"):
        lines.append("Datos del usuario:")
        for k, v in data["profile"].items():
            cog = data.get("cognitive_facts", {}).get(k, {})
            if isinstance(cog, dict) and cog.get("confidence", CONFIDENCE_INITIAL) < 0.15:
                continue
            lines.append(f"  {k}: {v['valor']}")
    if data.get("preferences"):
        lines.append("Preferencias:")
        for cat, vals in data["preferences"].items():
            lines.append(f"  {cat}: {', '.join(vals)}")
    if data.get("facts"):
        lines.append("Hechos recientes:")
        for h in data["facts"][-5:]:
            lines.append(f"  - {h['hecho']}")
    if data.get("corrections"):
        lines.append("Correcciones:")
        for c in data["corrections"][-3:]:
            if c.get("error") and c.get("correcto"):
                lines.append(f"  - '{c['error']}' -> '{c['correcto']}'")
    return json.dumps({"success": True, "context": "\n".join(lines) if lines else "No hay informacion aprendida aun"})

# ── learner_* (autolearner.py) ──────────────────────────────────────────


@register(
    name="learner_extract",
    description="Extraer informacion del usuario desde texto (nombre, trabajo, ubicacion, etc.)",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Texto del usuario"},
        },
        "required": ["text"],
    },
    tier="free",
)
def learner_extract(text: str) -> str:
    data = _load()
    text_lower = text.lower().strip()
    for kw in _SENSITIVE:
        if kw in text_lower:
            return json.dumps({"success": False, "message": "Contenido sensible, no se extrae"})
    changes = []
    for pattern, key_base in _PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        if key_base:
            value = m.group(1).strip().strip(",").strip(".").strip()
            if not value or len(value) > 80:
                continue
            old = data.setdefault("profile", {}).get(key_base, {}).get("valor")
            if old == value:
                continue
            data["profile"][key_base] = {
                "valor": value,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            _reinforce_cognitive(key_base, value, data)
            changes.append((key_base, value))
        else:
            key = m.group(1).strip().lower().replace(" ", "_")
            value = m.group(2).strip().strip(",").strip(".").strip()
            if not key or not value or len(key) > 40 or len(value) > 80:
                continue
            if any(kw in key for kw in _SENSITIVE):
                continue
            old = data.setdefault("profile", {}).get(key, {}).get("valor")
            if old == value:
                continue
            data["profile"][key] = {
                "valor": value,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            _reinforce_cognitive(key, value, data)
            changes.append((key, value))
    if changes:
        _save(data)
        return json.dumps({"success": True, "learned": changes, "message": "Aprendido: " + ", ".join(f"{k}={v}" for k, v in changes)})
    return json.dumps({"success": True, "learned": [], "message": "Sin informacion nueva para aprender"})


@register(
    name="learner_facts",
    description="Ver toda la informacion aprendida sobre el usuario",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def learner_facts() -> str:
    data = _load()
    profile = data.get("profile", {})
    if not profile:
        return json.dumps({"success": True, "facts": {}, "message": "Aun no se nada sobre ti"})
    flat = {k: v["valor"] if isinstance(v, dict) else v for k, v in profile.items()}
    lines = ["Lo que se de ti:"]
    for k, v in flat.items():
        lines.append(f"  {k}: {v}")
    return json.dumps({"success": True, "facts": flat})


@register(
    name="learner_forget",
    description="Olvidar un dato aprendido",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Clave a olvidar"},
        },
        "required": ["key"],
    },
    tier="free",
)
def learner_forget(key: str) -> str:
    data = _load()
    removed = False
    if key in data.get("profile", {}):
        del data["profile"][key]
        removed = True
    if key in data.get("cognitive_facts", {}):
        del data["cognitive_facts"][key]
        removed = True
    if removed:
        _save(data)
        return json.dumps({"success": True, "message": f"Olvidado: {key}"})
    return json.dumps({"success": False, "message": f"No tengo '{key}'"})

# ── cognitive_* (cognitive.py) ──────────────────────────────────────────


@register(
    name="cognitive_remember",
    description="Recordar un hecho sobre el usuario con nivel de confianza",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Clave del hecho (ej: nombre, trabajo)"},
            "value": {"type": "string", "description": "Valor del hecho"},
            "confidence": {"type": "number", "description": "Confianza inicial (0-1, default 0.5)"},
        },
        "required": ["key", "value"],
    },
    tier="premium",
)
def cognitive_remember(key: str, value: str, confidence: float = 0.5) -> str:
    data = _load()
    old = CONFIDENCE_INITIAL
    cog = data.setdefault("cognitive_facts", {})
    existing = cog.get(key)
    if existing:
        existing["value"] = value
        existing["confidence"] = min(CONFIDENCE_MAX, existing.get("confidence", old) + CONFIDENCE_BOOST)
        existing["times_mentioned"] = existing.get("times_mentioned", 0) + 1
        existing["last_updated"] = datetime.now().isoformat()
    else:
        entry = _make_cognitive_entry(value)
        entry["confidence"] = max(0.0, min(CONFIDENCE_MAX, confidence))
        cog[key] = entry
    data.setdefault("profile", {})[key] = {
        "valor": value,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _save(data)
    return json.dumps({"success": True, "message": f"Recordado: {key} = {value}"})


@register(
    name="cognitive_recall",
    description="Recuperar hechos sobre el usuario desde la memoria cognitiva",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Clave a buscar (opcional, devuelve todo si se omite)"},
        },
        "required": [],
    },
    tier="premium",
)
def cognitive_recall(key: str = "") -> str:
    data = _load()
    _run_decay(data)
    cog = data.get("cognitive_facts", {})
    if key:
        entry = cog.get(key)
        if isinstance(entry, dict):
            _apply_decay(entry)
            return json.dumps({
                "success": True,
                "key": key,
                "value": entry["value"],
                "confidence": entry.get("confidence", CONFIDENCE_INITIAL),
                "times_mentioned": entry.get("times_mentioned", 1),
            })
        return json.dumps({"success": False, "message": f"No recuerdo '{key}'"})
    if not cog:
        return json.dumps({"success": True, "facts": {}, "message": "Memoria cognitiva vacia"})
    active = {k: v for k, v in cog.items() if isinstance(v, dict) and v.get("confidence", 0) >= 0.15}
    lines = ["Memoria cognitiva activa:"]
    for k, v in sorted(active.items(), key=lambda x: -x[1].get("confidence", 0)):
        lines.append(f"  {k}: {v['value']} (confianza: {v['confidence']:.2f})")
    return json.dumps({"success": True, "facts": active})


@register(
    name="cognitive_snapshot",
    description="Obtener snapshot completo de la memoria cognitiva",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="premium",
)
def cognitive_snapshot() -> str:
    data = _load()
    _run_decay(data)
    cog = data.get("cognitive_facts", {})
    active = {k: v for k, v in cog.items() if isinstance(v, dict) and v.get("confidence", 0) >= 0.15}
    return json.dumps({
        "success": True,
        "facts_count": len(active),
        "total_facts": len(cog),
        "facts": active,
    })

# ── recall_* (recall.py) ────────────────────────────────────────────────


@register(
    name="recall_save",
    description="Guardar un fragmento de informacion para recuperacion posterior",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Contenido a guardar"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags para categorizar"},
            "source": {"type": "string", "description": "Fuente de la informacion"},
        },
        "required": ["content"],
    },
    tier="free",
)
def recall_save(content: str, tags: list = None, source: str = "") -> str:
    data = _load()
    entry = {
        "id": int(time.time()),
        "content": content,
        "tags": tags or [],
        "source": source,
        "timestamp": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data.setdefault("snippets", []).insert(0, entry)
    if len(data["snippets"]) > 500:
        data["snippets"] = data["snippets"][:500]
    _save(data)
    return json.dumps({"success": True, "id": entry["id"], "message": f"Guardado: {content[:60]}..."})


@register(
    name="recall_search",
    description="Buscar informacion guardada por texto o tags",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto a buscar"},
            "tag": {"type": "string", "description": "Filtrar por tag"},
            "limit": {"type": "integer", "description": "Maximo de resultados"},
        },
        "required": [],
    },
    tier="free",
)
def recall_search(query: str = "", tag: str = "", limit: int = 10) -> str:
    data = _load()
    snippets = data.get("snippets", [])
    if not snippets:
        return json.dumps({"success": True, "results": [], "message": "No hay informacion guardada"})
    results = snippets
    if query:
        q = query.lower()
        results = [d for d in results if q in d.get("content", "").lower()]
    if tag:
        results = [d for d in results if tag in d.get("tags", [])]
    if not results:
        return json.dumps({"success": True, "results": [], "message": "Sin resultados"})
    results = results[:limit]
    lines = [f"Resultados ({len(results)}):"]
    for d in results:
        tags_str = f" [{', '.join(d.get('tags', []))}]" if d.get("tags") else ""
        lines.append(f"  [{d.get('date','?')}]{tags_str} {d.get('content','')[:120]}")
    return json.dumps({"success": True, "results": results, "count": len(results)})


@register(
    name="recall_delete",
    description="Eliminar informacion guardada por ID",
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "integer", "description": "ID del item a eliminar"},
        },
        "required": ["item_id"],
    },
    tier="free",
)
def recall_delete(item_id: int) -> str:
    data = _load()
    snippets = data.get("snippets", [])
    before = len(snippets)
    data["snippets"] = [d for d in snippets if d.get("id") != item_id]
    if len(data["snippets"]) == before:
        return json.dumps({"success": False, "message": f"ID {item_id} no encontrado"})
    _save(data)
    return json.dumps({"success": True, "message": f"Eliminado item {item_id}"})

# ── user_profile (NEW) ──────────────────────────────────────────────────


@register(
    name="user_profile",
    description="Obtener el perfil completo del usuario con todos los datos aprendidos",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def user_profile() -> str:
    data = _load()
    _run_decay(data)
    profile = data.get("profile", {})
    preferences = data.get("preferences", {})
    corrections = data.get("corrections", [])
    facts = data.get("facts", [])
    cog_facts = data.get("cognitive_facts", {})
    snippets = data.get("snippets", [])

    active_cog = {k: v for k, v in cog_facts.items() if isinstance(v, dict) and v.get("confidence", 0) >= 0.15}

    summary = {
        "profile_fields": len(profile),
        "preference_categories": len(preferences),
        "corrections": len(corrections),
        "facts": len(facts),
        "cognitive_facts_active": len(active_cog),
        "cognitive_facts_total": len(cog_facts),
        "snippets": len(snippets),
    }

    return json.dumps({
        "success": True,
        "summary": summary,
        "profile": profile,
        "preferences": preferences,
        "corrections": corrections[-10:],
        "facts": facts[-10:],
        "cognitive_facts": {k: {
            "value": v["value"],
            "confidence": v.get("confidence", CONFIDENCE_INITIAL),
            "times_mentioned": v.get("times_mentioned", 1),
        } for k, v in active_cog.items()},
        "snippets": snippets[:10],
    })
