"""
updater.py — Simple module-based update system.
Polls backend for updates, downloads and hot-reloads changed modules.
Supports git pull (zero-config) and ZIP download fallback.
"""
import asyncio, json, logging, os, subprocess, sys, time, zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.updater")

_APP_DIR = Path(__file__).resolve().parent.parent
_VERSION_PATH = _APP_DIR / "version.txt"
_UPDATE_URL = None


def _read_version() -> str:
    try:
        path = _VERSION_PATH
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            path = base / "version.txt"
            if not path.exists():
                path = base / "xens_assistant" / "version.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "0.0.0"


def _write_version(version: str):
    try:
        _VERSION_PATH.write_text(version.strip(), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write version: {e}")


def get_current_version() -> str:
    return _read_version()


def set_update_url(url: str):
    global _UPDATE_URL
    _UPDATE_URL = url


# ── Git-based update ────────────────────────────────────────────

def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _is_git_repo() -> bool:
    try:
        r = subprocess.run(["git", "rev-parse", "--git-dir"],
                           cwd=str(_APP_DIR), capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def update_via_git() -> str:
    if not _has_git():
        return "Git not installed"
    if not _is_git_repo():
        return "Not a git repository"
    try:
        r = subprocess.run(["git", "pull", "--ff-only"],
                           cwd=str(_APP_DIR), capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            new_version = _detect_version_after_pull()
            if new_version:
                _write_version(new_version)
            return f"OK: {r.stdout[:200]}"
        return f"Error: {r.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "Timeout"
    except Exception as e:
        return f"Error: {e}"


def _detect_version_after_pull() -> Optional[str]:
    try:
        r = subprocess.run(["git", "describe", "--tags", "--always"],
                           cwd=str(_APP_DIR), capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


# ── ZIP-based update (backend download) ─────────────────────────

async def check_for_updates() -> dict:
    if not _UPDATE_URL:
        return {"error": "No update URL configured"}
    try:
        from ..core.utils import get_http_client
        url = f"{_UPDATE_URL.rstrip('/')}/api/update/check"
        r = await get_http_client().post(url, json={
            "current_version": _read_version(),
            "platform": sys.platform,
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "update_available": False}


async def download_and_apply(update_url: str) -> str:
    try:
        from ..core.utils import get_http_client
        logger.info(f"Downloading update from {update_url}...")
        r = await get_http_client().get(update_url, timeout=120)
        r.raise_for_status()
        zip_path = _APP_DIR / "_update.zip"
        zip_path.write_bytes(r.content)
        return _apply_zip(zip_path)
    except Exception as e:
        return f"Download failed: {e}"


def _apply_zip(zip_path: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(str(_APP_DIR))
        zip_path.unlink()
        new_version = _read_version()
        return f"Updated to {new_version}"
    except Exception as e:
        return f"Extract failed: {e}"


# ── Module hot-reload (update .py files without restart) ─────────

def reload_module(module_path: str) -> str:
    """Reload a single .py file by its dotted path (e.g. 'tools.web')."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        importlib.reload(mod)
        return f"Reloaded {module_path}"
    except Exception as e:
        return f"Failed to reload {module_path}: {e}"


def reload_changed(changed_files: list[str]) -> list[str]:
    results = []
    for f in changed_files:
        dotted = f.replace("/", ".").replace("\\", ".").replace(".py", "")
        if dotted.startswith("."):
            dotted = dotted[1:]
        results.append(reload_module(dotted))
    return results
