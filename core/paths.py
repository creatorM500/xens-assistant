"""core/paths.py — Directorio de datos del usuario con migración de marca.

Antes: ~/.xens  →  Ahora: ~/.ainslup
En el primer arranque, si existe el dir viejo y no el nuevo, se copia todo
(licencia, config, créditos, perfil, sesiones) para no perder nada.
"""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("ainslup.paths")

APP_NAME = "ainslup"
LEGACY_NAME = "xens"


def data_home() -> Path:
    return Path.home() / f".{APP_NAME}"


def legacy_home() -> Path:
    return Path.home() / f".{LEGACY_NAME}"


def ensure_migrated() -> Path:
    target = data_home()
    source = legacy_home()
    try:
        if not target.exists() and source.exists():
            shutil.copytree(source, target)
            logger.info("Migrated user data %s -> %s", source, target)
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Data migration failed: {e}")
        target.mkdir(parents=True, exist_ok=True)
    return target


DATA_HOME = ensure_migrated()
