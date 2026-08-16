import asyncio, logging, os, signal, sys
from pathlib import Path

import httpx

logger = logging.getLogger("xens.utils")

_http_clients = {}
_shutdown_tasks = []

def get_http_client():
    """httpx.AsyncClient bound to the CURRENT event loop.

    httpx clients are loop-bound; sharing one across loops (e.g. the
    auto-update thread running its own asyncio.run) breaks every request.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    client = _http_clients.get(loop)
    if client is None:
        client = httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={"User-Agent": "XensAssistant/1.0"},
        )
        _http_clients[loop] = client
    return client

async def close_http_client():
    """Close every cached client (each loop has its own)."""
    for loop, client in list(_http_clients.items()):
        try:
            await client.aclose()
        except Exception as e:
            logger.warning(f"Failed to close HTTP client for loop {loop}: {e}")
    _http_clients.clear()
    logger.debug("HTTP clients closed")

def close_closed_loop_clients():
    """Close clients whose event loop already died (e.g. the auto-update thread).

    The auto-update thread runs its own asyncio.run(); the AsyncClient it
    created is cached keyed by that (now closed) loop and would otherwise leak.
    """
    for loop, client in list(_http_clients.items()):
        if loop is not None and loop.is_closed():
            try:
                asyncio.run(client.aclose())
            except Exception as e:
                logger.warning(f"Failed to close orphan HTTP client: {e}")
            _http_clients.pop(loop, None)

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
        if p.is_relative_to(Path(b)):
            raise PermissionError(f"Access denied: {b}")
    return str(p)
