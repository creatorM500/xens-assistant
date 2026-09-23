"""
updater.py — Simple module-based update system.
Polls the Supabase Storage feed (version.json + xens-latest.zip) and
hot-replaces changed files with backup/rollback. Falls back to git pull
(zero-config) when the install is a git repository.
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


def is_git_repo() -> bool:
    return _is_git_repo()


def update_via_git() -> str:
    if not _has_git():
        return "Git not installed"
    if not _is_git_repo():
        return "Not a git repository"
    try:
        r = subprocess.run(["git", "pull", "--ff-only"],
                           cwd=str(_APP_DIR), capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            # Solo re-sellar version.txt si el pull trajo cambios de verdad;
            # si no, pisaría versiones beta/manual con el hash de git.
            if "Already up to date" not in (r.stdout or ""):
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


# ── ZIP-based update (Supabase Storage feed) ────────────────────
# Feed layout (public bucket, e.g. .../object/public/xens-updates):
#   version.json  -> {"version": "...", "zip": "xens-latest.zip", "sha256": "..."}
#   xens-latest.zip -> full app tree (extracted over _APP_DIR)

async def check_for_updates() -> dict:
    if not _UPDATE_URL:
        return {"error": "No update URL configured", "update_available": False}
    try:
        from ..core.utils import get_http_client
        r = await get_http_client().get(
            f"{_UPDATE_URL.rstrip('/')}/version.json?_t={int(time.time())}", timeout=10)
        r.raise_for_status()
        data = r.json()
        current = _read_version()
        available = bool(data.get("version")) and data.get("version") != current
        return {
            "update_available": available,
            "current_version": current,
            "version": data.get("version", ""),
            "sha256": data.get("sha256", ""),
            "filename": data.get("zip", "xens-latest.zip"),
        }
    except Exception as e:
        return {"error": str(e), "update_available": False}


async def download_and_apply(sha256: str = "", filename: str = "xens-latest.zip") -> str:
    if not _UPDATE_URL:
        return "No update URL configured"
    try:
        from ..core.utils import get_http_client
        url = f"{_UPDATE_URL.rstrip('/')}/{filename}?_t={int(time.time())}"
        logger.info(f"Downloading update from {url}...")
        r = await get_http_client().get(url, timeout=120)
        r.raise_for_status()
        content = r.content
        if sha256:
            import hashlib
            actual = hashlib.sha256(content).hexdigest()
            if actual.lower() != sha256.lower():
                return f"Checksum mismatch: expected {sha256}, got {actual}"
        return _apply_zip(content)
    except Exception as e:
        return f"Download failed: {e}"


async def auto_update_zip() -> str:
    info = await check_for_updates()
    if not info.get("update_available"):
        return f"Up to date ({info.get('current_version', '?')})"
    logger.info(f"Update found: {info.get('version')} (current: {info.get('current_version')})")
    return await download_and_apply(info.get("sha256", ""), info.get("filename", "xens-latest.zip"))


# ── EXE update (beta): descarga + swap al reiniciar ────────────────────
# El feed version.json puede traer:
#   {"version": "...", "exe": {"version": "...", "file": "Xens-beta.exe", "sha256": "..."}}
# Windows no deja sobrescribir un exe en ejecución: se descarga como
# <exe>.new.exe y un .bat lo intercambia al salir (patrón clásico).

def _exe_path() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except Exception:
        return None


async def check_exe_update() -> dict:
    """Compara el exe congelado con el feed. Solo tiene sentido en frozen."""
    current = _read_version()
    out = {"exe_update": False, "current_version": current,
           "exe_version": "", "exe_file": "", "exe_bytes": 0}
    exe = _exe_path()
    if exe is None:
        out["note"] = "not frozen (dev)"
        return out
    if not _UPDATE_URL:
        out["error"] = "No update URL configured"
        return out
    try:
        from ..core.utils import get_http_client
        r = await get_http_client().get(
            f"{_UPDATE_URL.rstrip('/')}/version.json?_t={int(time.time())}", timeout=15)
        r.raise_for_status()
        data = r.json()
        meta = data.get("exe") or {}
        ver = str(meta.get("version") or "")
        out["exe_version"] = ver
        out["exe_file"] = str(meta.get("file") or "")
        out["exe_sha256"] = str(meta.get("sha256") or "")
        out["exe_parts"] = list(meta.get("parts") or [])
        out["exe_bytes"] = int(meta.get("bytes") or 0)
        staged = exe.parent / (exe.name + ".new.exe")
        out["staged"] = staged.exists()
        out["exe_update"] = bool(ver) and ver != current and not staged.exists()
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


async def download_exe_update(url_path: str = "", sha256: str = "") -> dict:
    """Descarga el exe nuevo como <exe>.new.exe (verifica sha256)."""
    exe = _exe_path()
    if exe is None:
        return {"ok": False, "error": "not frozen (dev)"}
    if not _UPDATE_URL:
        return {"ok": False, "error": "No update URL configured"}
    try:
        from ..core.utils import get_http_client
        info = await check_exe_update()
        if info.get("error"):
            return {"ok": False, "error": info["error"]}
        filename = url_path or info.get("exe_file") or ""
        want_sha = sha256 or info.get("exe_sha256") or ""
        if not filename:
            return {"ok": False, "error": "Feed sin exe para esta versión"}
        parts = info.get("exe_parts") or [filename]
        blobs = []
        for part in parts:
            url = f"{_UPDATE_URL.rstrip('/')}/{part}?_t={int(time.time())}"
            logger.info(f"Downloading exe update part {part}...")
            r = await get_http_client().get(url, timeout=600)
            r.raise_for_status()
            blobs.append(r.content)
        content = b"".join(blobs)
        if want_sha:
            import hashlib
            actual = hashlib.sha256(content).hexdigest()
            if actual.lower() != want_sha.lower():
                return {"ok": False, "error": "Checksum mismatch en el exe"}
        staged = exe.parent / (exe.name + ".new.exe")
        staged.write_bytes(content)
        return {"ok": True, "staged": str(staged), "bytes": len(content)}
    except Exception as e:
        return {"ok": False, "error": f"Download failed: {e}"}


def stage_exe_swap_and_exit() -> str:
    """Crea el .bat que intercambia el exe al salir y termina el proceso.

    Uso: tras download_exe_update OK, la UI pide reiniciar → el servidor
    llama aquí: genera _update_swap.bat, lo lanza detached y hace os._exit.
    El .bat espera que el exe se libere, mueve .new.exe sobre el exe,
    relanza y se autoborra.
    """
    import subprocess
    exe = _exe_path()
    if exe is None:
        return "not frozen (dev)"
    staged = exe.parent / (exe.name + ".new.exe")
    if not staged.exists():
        return "no staged update"
    bat = exe.parent / "_update_swap.bat"
    bat.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'move /Y "{staged}" "{exe}" >nul\r\n'
        f'start "" "{exe}" --app\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    try:
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception:
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent))
    logger.info("Swap de exe programado; saliendo para aplicar")
    os._exit(0)


def _apply_zip(content: bytes) -> str:
    import io
    import shutil
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in Path(name).parts:
                    return f"Unsafe path in update zip: {info.filename}"
            new_dir = _APP_DIR / "_update_new"
            backup_dir = _APP_DIR / "_update_backup"
            for d in (new_dir, backup_dir):
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            new_dir.mkdir()
            zf.extractall(str(new_dir))

        replaced = []
        try:
            for f in new_dir.rglob("*"):
                rel = f.relative_to(new_dir)
                target = _APP_DIR / rel
                if f.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    bak = backup_dir / rel
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(bak))
                    replaced.append((target, bak))
                shutil.move(str(f), str(target))
        except Exception as e:
            for target, bak in reversed(replaced):
                if bak.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(bak), str(target))
            shutil.rmtree(new_dir, ignore_errors=True)
            return f"Apply failed, rolled back: {e}"

        shutil.rmtree(new_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        return f"Updated to {_read_version()}"
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
