import asyncio, logging, os, signal, sys
from pathlib import Path

import httpx

logger = logging.getLogger("xens.utils")

_http_client = None
_shutdown_tasks = []

def get_http_client():
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={"User-Agent": "XensAssistant/1.0"},
        )
    return _http_client

async def close_http_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
        logger.debug("HTTP client closed")

def register_shutdown(coro):
    _shutdown_tasks.append(coro)

async def shutdown_all():
    logger.info("Shutting down...")
    for coro in _shutdown_tasks:
        try:
            await coro
        except Exception as e:
            logger.warning(f"Shutdown task error: {e}")
    await close_http_client()
    logger.info("Shutdown complete")

def truncate(text, max_len=500):
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."

def format_size(bytes_val):
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}TB"

def safe_path(path_str, base=None):
    from pathlib import Path
    p = Path(path_str)
    if not p.is_absolute():
        base = Path(base) if base else Path.cwd()
        p = base / p
    p = p.resolve()
    blocked = {"C:\\Windows", "C:\\Windows\\System32", "C:\\Program Files", "C:\\Program Files (x86)"}
    for b in blocked:
        if str(p).lower().startswith(b.lower()):
            raise PermissionError(f"Access denied: {b}")
    return str(p)
