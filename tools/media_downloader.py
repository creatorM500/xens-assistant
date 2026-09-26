import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse
from .registry import register

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), ".ainslup", "downloads")
HISTORY_FILE = os.path.join(DOWNLOAD_DIR, "_history.json")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _validate_url(url: str) -> str:
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("URL es requerida")
    url = url.strip()
    if not _URL_RE.match(url):
        raise ValueError("La URL debe empezar con http:// o https://")
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("La URL no es válida (sin host)")
    return url

try:
    import yt_dlp
    _HAS_YDL = True
except Exception:
    _HAS_YDL = False


def _get_ytdlp():
    """Devuelve el módulo yt_dlp, instalándolo si hay consentimiento."""
    if _HAS_YDL:
        return yt_dlp
    try:
        from ..core.dependencies import ensure
        ensure("yt_dlp")
        import yt_dlp as _ydl
        return _ydl
    except Exception:
        return None

_PROGRESS = {}


def _unique_path(ext: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    return os.path.join(DOWNLOAD_DIR, f"download_{ts}{ext}")


def _load_history() -> list:
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save_history(entry: dict):
    h = _load_history()
    h.insert(0, entry)
    if len(h) > 200:
        h = h[:200]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


def _progress_hook(d):
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes", 0)
        pct = int(downloaded / max(total, 1) * 100) if total else 0
        _PROGRESS[d["info_dict"].get("id", "")] = {
            "pct": pct, "downloaded": downloaded, "total": total, "speed": d.get("speed", 0),
        }


@register(
    name="list_formats",
    description="Listar formatos disponibles de un video URL",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL del video"},
        },
        "required": ["url"],
    },
    tier="premium",
)
def list_formats(url: str) -> str:
    ydl_mod = _get_ytdlp()
    if not ydl_mod:
        return "yt-dlp no disponible. Aceptá la instalación de dependencias en Configuración."
    try:
        url = _validate_url(url)
        ydl = ydl_mod.YoutubeDL({"quiet": True, "no_warnings": True})
        info = ydl.extract_info(url, download=False)
        lines = [f"Titulo: {info.get('title', '?')}"]
        if info.get("duration"):
            d = info["duration"]
            lines.append(f"Duracion: {d // 60}:{d % 60:02d}")
        seen = set()
        for f in info.get("formats", []):
            ext = f.get("ext", "?")
            note = f.get("format_note", "")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            if ext == "mhtml":
                continue
            key = f"{ext}_{note}_{vcodec}_{acodec}"
            if key in seen:
                continue
            seen.add(key)
            tbr = f.get("tbr", 0)
            size = f.get("filesize", 0) or f.get("filesize_approx", 0)
            size_str = f" ({size // 1024 // 1024} MB)" if size else ""
            type_str = "VID" if vcodec != "none" else "AUDIO" if acodec != "none" else "?"
            lines.append(f"  {f['format_id']}: {ext} {note} {type_str} {tbr:.0f}k{size_str}")
        return "\n".join(lines[:30])
    except Exception as e:
        return f"Error: {e}"


@register(
    name="download_video",
    description="Descargar video o audio de una URL",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL del video"},
            "format_id": {"type": "string", "description": "ID del formato (default: best)"},
            "audio_only": {"type": "boolean", "description": "Solo audio (MP3)"},
        },
        "required": ["url"],
    },
    tier="premium",
)
def download_video(url: str, format_id: str = "best", audio_only: bool = False) -> str:
    ydl_mod = _get_ytdlp()
    if not ydl_mod:
        return "yt-dlp no disponible. Aceptá la instalación de dependencias en Configuración."
    try:
        url = _validate_url(url)
        if audio_only:
            try:
                from ..core.dependencies import ensure
                ensure("ffmpeg")
            except Exception as e:
                return f"FFmpeg necesario para extraer audio: {e}"
        ext = "mp3" if audio_only else "mp4"
        output = _unique_path(f".{ext}")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": output.replace(f".{ext}", ".%(ext)s"),
            "progress_hooks": [_progress_hook],
        }
        if audio_only:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        elif format_id != "best":
            opts["format"] = format_id
        else:
            opts["format"] = "best[ext=mp4]/best"

        with ydl_mod.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", url)

        final = output
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, f)
            if time.time() - os.path.getmtime(fp) < 30 and os.path.getsize(fp) > 1000:
                final = fp
                break

        if not os.path.isfile(final):
            return "Error: archivo no encontrado tras descarga"

        fsize = os.path.getsize(final)
        fname = os.path.basename(final)
        _save_history({"url": url, "title": title, "file": fname, "type": "audio" if audio_only else "video", "size": fsize, "date": time.time()})
        return f"Descargado: {title}\nArchivo: {fname}\nTamano: {fsize // 1024 // 1024} MB"
    except Exception as e:
        return f"Error descargando: {e}"


@register(
    name="download_progress",
    description="Ver progreso de descargas activas",
    parameters={"type": "object", "properties": {}, "required": []},
    tier="free",
)
def download_progress() -> str:
    if not _PROGRESS:
        return "Sin descargas activas"
    lines = ["Descargas activas:"]
    for fid, p in list(_PROGRESS.items()):
        if p["pct"] >= 100:
            del _PROGRESS[fid]
            continue
        speed = p.get("speed", 0)
        speed_str = f"{speed // 1024 // 1024} MB/s" if speed > 1024 * 1024 else f"{speed // 1024} KB/s" if speed else "?"
        lines.append(f"  {fid[:8]}: {p['pct']}% ({speed_str})")
    return "\n".join(lines) if len(lines) > 1 else "Sin descargas activas"


@register(
    name="download_history",
    description="Historial de descargas",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Maximo de resultados"},
        },
        "required": [],
    },
    tier="free",
)
def download_history(limit: int = 10) -> str:
    h = _load_history()
    if not h:
        return "Sin historial de descargas"
    lines = [f"Ultimas {min(limit, len(h))} descargas:"]
    for e in h[:limit]:
        ts = datetime.fromtimestamp(e.get("date", 0)).strftime("%H:%M")
        size = e.get("size", 0)
        size_str = f"{size // 1024 // 1024} MB" if size > 1024 * 1024 else f"{size // 1024} KB" if size else "?"
        lines.append(f"  [{ts}] {e.get('type','?')} {e.get('title','?')[:50]} ({size_str})")
    return "\n".join(lines)
