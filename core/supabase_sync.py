"""supabase_sync.py — Sincronización de conversaciones por cuenta (Supabase REST).

Config-driven: solo se activa si la config tiene un proyecto Supabase:
    config["supabase"] = {"url": "...", "anon_key": "..."}

Tabla esperada (ver supabase/migrations):
    conversations (
        id uuid pk, uid text, title text, created_at timestamptz,
        updated_at timestamptz, data jsonb
    )
    RLS: el usuario solo accede a sus filas (uid = auth.uid()).

Todo I/O es async (httpx) y los errores se degradan a "off" sin romper el chat.
"""
import json, logging
from typing import Optional

import httpx

logger = logging.getLogger("xens.supabase")

_ENABLED = False
_BASE = ""
_HEADERS = {}


def configure(url: str = "", anon_key: str = "") -> bool:
    global _ENABLED, _BASE, _HEADERS
    url = (url or "").strip().rstrip("/")
    anon_key = (anon_key or "").strip()
    if not url or not anon_key:
        _ENABLED = False
        _BASE = ""
        _HEADERS = {}
        return False
    _BASE = url
    _HEADERS = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
    }
    _ENABLED = True
    logger.info("Supabase sync activo: %s", url)
    return True


def is_enabled() -> bool:
    return _ENABLED


def _configure_from_config():
    try:
        from .config import config
        sb = (config.get("supabase", {}) or {})
        configure(sb.get("url", ""), sb.get("anon_key", ""))
    except Exception as e:
        logger.warning("Supabase sync no configurado: %s", e)


_configure_from_config()


async def _request(method: str, path: str, **kwargs) -> Optional[dict]:
    if not _ENABLED:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{_BASE}{path}", headers=_HEADERS, **kwargs)
            if r.status_code >= 400:
                logger.warning("Supabase %s %s -> %s", method, path, r.status_code)
                return None
            if r.status_code == 204 or not r.content:
                return {}
            return r.json()
    except Exception as e:
        logger.warning("Supabase request falló: %s", e)
        return None


def _postgrest_filter(path: str, uid: str) -> str:
    return f"{path}?uid=eq.{uid}&order=updated_at.desc"


async def save_conversation(uid: str, conversation: dict) -> bool:
    """Upsert de una conversación de la cuenta (idempotente por id)."""
    if not _ENABLED:
        return False
    payload = {
        "uid": uid,
        "id": str(conversation.get("id") or ""),
        "title": str(conversation.get("title") or "Sin título")[:200],
        "data": conversation,
        "updated_at": conversation.get("updated_at") or _now_iso(),
    }
    if not payload["id"]:
        return False
    res = await _request(
        "POST",
        "/rest/v1/conversations",
        params={"on_conflict": "id"},
        json=payload,
    )
    return res is not None


async def list_conversations(uid: str, limit: int = 100) -> list:
    if not _ENABLED:
        return []
    res = await _request(
        "GET",
        f"/rest/v1/conversations?uid=eq.{uid}&select=id,title,updated_at&order=updated_at.desc&limit={int(limit)}",
    )
    if not isinstance(res, list):
        return []
    return res


async def get_conversation(uid: str, conv_id: str) -> Optional[dict]:
    if not _ENABLED:
        return None
    res = await _request(
        "GET",
        f"/rest/v1/conversations?uid=eq.{uid}&id=eq.{conv_id}&select=data&limit=1",
    )
    if isinstance(res, list) and res:
        return res[0].get("data")
    return None


async def delete_conversation(uid: str, conv_id: str) -> bool:
    if not _ENABLED:
        return False
    res = await _request(
        "DELETE",
        f"/rest/v1/conversations?uid=eq.{uid}&id=eq.{conv_id}",
    )
    return res is not None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()