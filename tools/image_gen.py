"""
image_gen.py — Generación de imágenes vía Pollinations (sin GPU local).

Modelo gratis por defecto (sdxl-lightning-free, ~0 Pollen).
Modelos de pago (flux.1-schnell, ~0.002 Pollen) para tiers altos.
Guarda en ~/.ainslup/downloads y devuelve la ruta en JSON.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .registry import register

logger = logging.getLogger("xens.tools.image_gen")

FREE_MODEL = "community/scriptsnsenses-sys/sdxl-lightning-free"
PRO_MODEL = "black-forest-labs/flux.1-schnell"
_MODEL_ALIASES = {"": FREE_MODEL, "free": FREE_MODEL, "sdxl": FREE_MODEL,
                  "flux": PRO_MODEL, "pro": PRO_MODEL, "schnell": PRO_MODEL}

DOWNLOAD_DIR = Path.home() / ".ainslup" / "downloads"


def _polli_key() -> str:
    try:
        from ..core.config import config
        return ((config.get("llm", {}) or {}).get("pollinations", {}) or {}).get("api_key", "") or ""
    except Exception:
        return ""


@register(name="generate_image",
          description="Generate an image from a text prompt and save it to disk. Returns JSON with the file path. Free model by default; use model='flux' for higher quality.",
          tier="free", timeout=180)
def generate_image(prompt: str, model: str = "", size: str = "1024x1024") -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"success": False, "error": "prompt required"})
    key = _polli_key()
    if not key:
        return json.dumps({"success": False, "error": "Pollinations API key not configured"})
    mdl = _MODEL_ALIASES.get((model or "").strip().lower(), (model or "").strip() or FREE_MODEL)
    try:
        w, h = size.lower().replace(" ", "").split("x")
        w, h = max(256, min(2048, int(w))), max(256, min(2048, int(h)))
    except Exception:
        w, h = 1024, 1024
    url = ("https://gen.pollinations.ai/image/%s?model=%s&width=%d&height=%d&nologo=true&key=%s"
           % (urllib.parse.quote(prompt), urllib.parse.quote(mdl, safe=""), w, h, key))
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
        resp = urllib.request.urlopen(req, timeout=150)
        data = resp.read()
        ctype = (resp.headers.get("Content-Type") or "")
        if "image" not in ctype or len(data) < 5000:
            return json.dumps({"success": False, "error": f"upstream returned {ctype} ({len(data)} bytes)"})
    except Exception as e:
        logger.warning("generate_image upstream falló: %s", e)
        return json.dumps({"success": False, "error": f"image upstream failed: {e}"})
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = str(DOWNLOAD_DIR / f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception as e:
        return json.dumps({"success": False, "error": f"cannot save image: {e}"})
    return json.dumps({"success": True, "path": path, "model": mdl, "bytes": len(data),
                       "note": "Show the image to the user from this path"})
