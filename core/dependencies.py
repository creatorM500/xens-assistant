"""core/dependencies.py — Detección, consentimiento e instalación de dependencias.

Ainslup necesita algunos componentes externos para funciones avanzadas:
  - FFmpeg (binario portable, ~110 MB) → edición de video/audio.
  - yt-dlp (pip) → descargas de video de YouTube y otras plataformas.
  - Paquetes core (pip) → aiohttp, httpx, comtypes (motor).

Flujo:
  1. El usuario acepta la instalación (UI → POST /api/deps/install).
  2. Las instalaciones corren en un thread de fondo; el UI consulta
     GET /api/deps hasta que terminan.
  3. Las tools usan ensure(dep_id) en runtime: si está, sigue marcha;
     si falta y el usuario dio consentimiento, se instala sola;
     si no, lanza un error claro apuntando a Configuración.

El estado vive en ~/.ainslup/config.json → "deps": {"approved": bool,
"installed": [ids]}.
"""
import json
import logging
import shutil
import subprocess
import sys
import threading
from importlib.util import find_spec
from pathlib import Path

from ..core.config import config, save as save_config
from ..tools.registry import ToolError

logger = logging.getLogger("xens.deps")

BIN_DIR = Path.home() / ".ainslup" / "bin"
_REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements-core.txt"

_CORE_MODULES = ("aiohttp", "httpx", "comtypes")

# Estado transitorio (en memoria)
_status = {
    "installing": [],          # ids en instalación
    "_lock": threading.Lock(),
}


def _find_binary(name: str):
    exe = shutil.which(name)
    if exe:
        return exe
    cand = BIN_DIR / (name + (".exe" if sys.platform == "win32" else ""))
    return str(cand) if cand.exists() else None


def _pip_install(args):
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
           "--quiet", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise ToolError(
            "pip falló: " + (proc.stderr or proc.stdout or "")[-300:],
            code="PIP_INSTALL_FAIL",
        )


def _install_reqs():
    _pip_install(["-r", str(_REQUIREMENTS)])


def _install_ffmpeg():
    from ..tools.video import _download_ffmpeg
    _download_ffmpeg()


def _install_ytdlp():
    _pip_install(["yt-dlp"])


# Registro declarativo de dependencias
DEPS = [
    {
        "id": "ffmpeg",
        "kind": "binario",
        "name": "FFmpeg",
        "desc": "Edición de video y audio: cortar, unir, convertir, extraer audio, GIFs",
        "size": "~110 MB",
        "check": lambda: bool(_find_binary("ffmpeg") and _find_binary("ffprobe")),
        "install": _install_ffmpeg,
    },
    {
        "id": "yt_dlp",
        "kind": "pip",
        "name": "yt-dlp",
        "desc": "Descargas de video desde YouTube y otras plataformas",
        "size": "~3 MB",
        "check": lambda: find_spec("yt_dlp") is not None,
        "install": _install_ytdlp,
    },
    {
        "id": "core",
        "kind": "pip",
        "name": "Paquetes del motor",
        "desc": "Dependencias Python del motor (aiohttp, httpx, comtypes)",
        "size": "~15 MB",
        "check": lambda: all(find_spec(m) is not None for m in _CORE_MODULES),
        "install": _install_reqs,
    },
]

_DEPS_BY_ID = {d["id"]: d for d in DEPS}


def _state() -> dict:
    st = config.get("deps")
    if not isinstance(st, dict):
        st = {}
        config["deps"] = st
    st.setdefault("approved", False)
    st.setdefault("installed", [])
    return st


def _save_state():
    try:
        save_config(config)
    except Exception as e:
        logger.warning(f"Failed to save deps state: {e}")


def consent_given() -> bool:
    return bool(_state().get("approved"))


def is_installed(dep_id: str) -> bool:
    dep = _DEPS_BY_ID.get(dep_id)
    if not dep:
        return False
    if dep_id in _state().get("installed", []):
        return True
    return bool(dep["check"]())


def status() -> dict:
    with _status["_lock"]:
        installing = list(_status["installing"])
    return {
        "consent": consent_given(),
        "installing": installing,
        "deps": [
            {
                "id": d["id"],
                "name": d["name"],
                "kind": d["kind"],
                "size": d["size"],
                "desc": d["desc"],
                "installed": is_installed(d["id"]),
            }
            for d in DEPS
        ],
    }


def request_install(dep_ids: list, consent: bool = True) -> dict:
    """Arranca la instalación en background. Devuelve el estado inmediato."""
    if not isinstance(dep_ids, list) or not dep_ids:
        dep_ids = [d["id"] for d in DEPS]
    unknown = [i for i in dep_ids if i not in _DEPS_BY_ID]
    if unknown:
        return {"started": False, "error": f"Dependencias desconocidas: {unknown}"}
    pending = [i for i in dep_ids if not is_installed(i)]

    if consent:
        _state()["approved"] = True
        _save_state()

    with _status["_lock"]:
        installing = set(_status["installing"])
        todo = [i for i in pending if i not in installing]
        if todo:
            _status["installing"].extend(todo)
    if not todo:
        return {"started": False, "already_installed": True, **status()}

    threading.Thread(target=_run_install, args=(todo,), daemon=True).start()
    return {"started": True, "installing": todo, **status()}


def _run_install(dep_ids: list):
    for dep_id in dep_ids:
        try:
            logger.info("Installing dependency: %s", dep_id)
            _DEPS_BY_ID[dep_id]["install"]()
            st = _state()
            if dep_id not in st["installed"]:
                st["installed"].append(dep_id)
            _save_state()
            logger.info("Dependency installed: %s", dep_id)
        except Exception as e:
            logger.error("Dependency install failed (%s): %s", dep_id, e)
        finally:
            with _status["_lock"]:
                try:
                    _status["installing"].remove(dep_id)
                except ValueError:
                    pass


def ensure(dep_id: str) -> bool:
    """Uso en runtime desde las tools. Instala sola si hay consentimiento."""
    dep = _DEPS_BY_ID.get(dep_id)
    if dep and dep["check"]():
        st = _state()
        if dep_id not in st["installed"]:
            st["installed"].append(dep_id)
            _save_state()
        return True
    name = dep["name"] if dep else dep_id
    if not consent_given():
        raise ToolError(
            f"Falta la dependencia '{name}'. Aceptá la instalación de "
            "dependencias en Configuración → Dependencias.",
            code="DEPS_NOT_APPROVED",
        )
    request_install([dep_id], consent=True)
    with _status["_lock"]:
        installing = dep_id in _status["installing"]
    if not is_installed(dep_id) and installing:
        raise ToolError(
            f"'{name}' se está instalando en segundo plano. "
            "Intenta de nuevo en unos segundos.",
            code="DEPS_INSTALLING",
        )
    if not is_installed(dep_id):
        raise ToolError(
            f"No se pudo instalar '{name}' automǭticamente. "
            "Revisǭ Configuraci��n ��' Dependencias para reintentar.",
            code="DEPS_INSTALL_FAIL",
        )
    return True


def summary() -> str:
    """Breakdown corto para las herramientas/logs."""
    parts = []
    for d in DEPS:
        mark = "OK" if is_installed(d["id"]) else "FALTA"
        parts.append(f"{d['id']}={mark}")
    return ", ".join(parts)