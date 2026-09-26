"""tools/video.py — Edición de video/audio con ffmpeg.

Suite de herramientas para cortar, unir, convertir, escalar, cambiar
velocidad, extraer audio, generar miniaturas y GIFs.

ffmpeg/ffprobe: se buscan en PATH y en ~/.ainslup/bin. Si no existen en
Windows se descargan automáticamente (build portable) al primer uso;
en Linux/macOS se indica el comando para instalarlos.

Todas las herramientas devuelven JSON y pertenecen al tier "pro".
"""
import json
import math
import os
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from .registry import register, ToolError

BIN_DIR = Path.home() / ".ainslup" / "bin"
OUT_DIR = Path.home() / ".ainslup" / "video"

_FFMPEG_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

_BLOCKED_DIRS = (
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\Users\\Default", "C:\\Recovery",
)


def _resolve(path_str: str) -> Path:
    if not path_str or not isinstance(path_str, str):
        raise ToolError("Path must be a non-empty string")
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    for b in _BLOCKED_DIRS:
        if str(p).lower().startswith(b.lower()):
            raise ToolError(f"Access denied to system directory: {b}")
    return p


def _find_bin(name: str):
    exe = shutil.which(name)
    if exe:
        return exe
    cand = BIN_DIR / (name + (".exe" if os.name == "nt" else ""))
    return str(cand) if cand.exists() else None


def _download_ffmpeg():
    """Download a portable Windows build of ffmpeg+ffprobe into ~/.ainslup/bin."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BIN_DIR / "ffmpeg_download.zip"
    try:
        print(f"[video] Descargando ffmpeg portable ({_FFMPEG_ZIP_URL}) ...")
        with urllib.request.urlopen(_FFMPEG_ZIP_URL, timeout=120) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        with zipfile.ZipFile(tmp) as z:
            for n in z.namelist():
                base = os.path.basename(n)
                if base in ("ffmpeg.exe", "ffprobe.exe"):
                    with z.open(n) as src, open(BIN_DIR / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        tmp.unlink(missing_ok=True)
        print("[video] ffmpeg listo en ~/.ainslup/bin")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ToolError(
            f"No se pudo descargar ffmpeg automáticamente ({e}). "
            "Descargalo de https://www.gyan.dev/ffmpeg/builds/ y agregalo al PATH.",
            code="FFMPEG_DOWNLOAD_FAIL",
        )


def _ensure_ffmpeg():
    """Devuelve las rutas de ffmpeg/ffprobe, instalándolas si hay consentimiento."""
    from ..core.dependencies import ensure
    ensure("ffmpeg")
    ffmpeg, ffprobe = _find_bin("ffmpeg"), _find_bin("ffprobe")
    if not (ffmpeg and ffprobe):
        raise ToolError(
            "ffmpeg/ffprobe no están disponibles. Revisá Configuración → Dependencias.",
            code="FFMPEG_MISSING",
        )
    return ffmpeg, ffprobe


def _run(cmd, timeout=1200):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"ffmpeg excedió el tiempo límite ({timeout}s)", code="FFMPEG_TIMEOUT")
    if proc.returncode != 0:
        raise ToolError("ffmpeg falló: " + (proc.stderr or "")[-600:], code="FFMPEG_ERROR")
    return proc


def _out_path(src: Path, suffix: str, custom: str = "") -> Path:
    if custom:
        return _resolve(custom)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUT_DIR / f"{src.stem}_{ts}{suffix}"


def _check_exists(p: Path):
    if not p.exists() or not p.is_file():
        raise ToolError(f"File not found: {p}", code="FILE_NOT_FOUND")


def _ok(**extra):
    return json.dumps({"success": True, **extra}, ensure_ascii=False)


@register(
    name="video_info",
    description="Obtener información de un archivo de video o audio (duración, resolución, codecs)",
    tier="pro",
    timeout=120,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
        },
        "required": ["path"],
    },
)
def video_info(path: str) -> str:
    ffmpeg, ffprobe = _ensure_ffmpeg()
    p = _resolve(path)
    _check_exists(p)
    proc = _run([ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(p)], timeout=120)
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise ToolError("No se pudo leer la información del archivo (¿no es un video válido?)",
                        code="FFPROBE_PARSE")
    if not isinstance(data, dict):
        raise ToolError("Salida de ffprobe inesperada", code="FFPROBE_PARSE")
    fmt = data.get("format", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    info = {
        "file": str(p),
        "size_mb": round(int(fmt.get("size", 0)) / 1048576, 2),
        "duration_sec": float(fmt.get("duration", 0) or 0),
        "video_codec": (vstream or {}).get("codec_name"),
        "width": (vstream or {}).get("width"),
        "height": (vstream or {}).get("height"),
        "fps": (vstream or {}).get("avg_frame_rate"),
        "audio_codec": (astream or {}).get("codec_name"),
        "audio_channels": (astream or {}).get("channels"),
    }
    return _ok(**info)


@register(
    name="video_cut",
    description="Recortar un segmento de un video o audio (start/end en segundos o HH:MM:SS)",
    tier="pro",
    timeout=900,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video original"},
            "start": {"type": "string", "description": "Inicio del recorte, ej. '12' o '00:00:12'"},
            "end": {"type": "string", "description": "Fin del recorte, ej. '47' o '00:00:47'"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path", "start", "end"],
    },
)
def video_cut(path: str, start: str, end: str, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    p = _resolve(path)
    _check_exists(p)
    out = _out_path(p, "_cut.mp4", output)
    proc = _run([ffmpeg, "-y", "-i", str(p), "-ss", start, "-to", end,
                 "-c", "copy", str(out)])
    return _ok(output=str(out), input=str(p))


@register(
    name="video_concat",
    description="Unir dos o más videos en uno solo (se re-codifican para garantizar compatibilidad)",
    tier="pro",
    timeout=1800,
    parameters={
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "Lista de rutas de videos a unir (en orden)"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["paths"],
    },
)
def video_concat(paths: list, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    if not isinstance(paths, list) or len(paths) < 2:
        raise ToolError("Se necesitan al menos 2 videos para unir")
    resolved = [_resolve(x) for x in paths]
    for p in resolved:
        _check_exists(p)
    out = _out_path(resolved[0], "_joined.mp4", output)

    inputs = []
    for p in resolved:
        inputs += ["-i", str(p)]
    n = len(resolved)
    chain = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filt = f"{chain}concat=n={n}:v=1:a=1[v][a]"
    try:
        proc = _run([ffmpeg, "-y", *inputs, "-filter_complex", filt,
                     "-map", "[v]", "-map", "[a]", str(out)])
    except ToolError:
        # algún archivo sin audio: reintentar solo video
        chain = "".join(f"[{i}:v:0]" for i in range(n))
        filt = f"{chain}concat=n={n}:v=1:a=0[v]"
        proc = _run([ffmpeg, "-y", *inputs, "-filter_complex", filt,
                     "-map", "[v]", str(out)])
    return _ok(output=str(out), files_joined=n)


@register(
    name="video_extract_audio",
    description="Extraer el audio de un video a mp3, wav, m4a u ogg",
    tier="pro",
    timeout=900,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "format": {"type": "string", "enum": ["mp3", "wav", "m4a", "ogg"],
                       "description": "Formato de audio de salida"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path", "format"],
    },
)
def video_extract_audio(path: str, format: str = "mp3", output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    codecs = {"mp3": "libmp3lame", "wav": "pcm_s16le", "m4a": "aac", "ogg": "libvorbis"}
    p = _resolve(path)
    _check_exists(p)
    out = _out_path(p, f".{format}", output)
    proc = _run([ffmpeg, "-y", "-i", str(p), "-vn",
                 "-acodec", codecs[format], str(out)])
    return _ok(output=str(out), format=format)


@register(
    name="video_speed",
    description="Cambiar la velocidad de un video (0.25x a 4x), manteniendo el tono del audio",
    tier="pro",
    timeout=900,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "factor": {"type": "number", "description": "Velocidad: 1.0 = normal, 2.0 = doble"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path", "factor"],
    },
)
def video_speed(path: str, factor: float, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    if not (0.25 <= float(factor) <= 4.0):
        raise ToolError("factor debe estar entre 0.25 y 4.0")
    p = _resolve(path)
    _check_exists(p)
    out = _out_path(p, f"_x{factor}.mp4", output)

    # atempo solo acepta 0.5..2.0: encadenar con la raíz n-ésima
    # para que el producto de atempos sea exactamente `f`.
    f = float(factor)
    if f > 2.0:
        n = math.ceil(f / 2.0)
    elif f < 0.5:
        n = math.ceil(0.5 / f)
    else:
        n = 1
    step = f ** (1.0 / n)
    audio_filt = ",".join(f"atempo={step:.4f}" for _ in range(n))
    filt = f"[0:v]setpts={1.0/f:.4f}*PTS[v];[0:a]{audio_filt}[a]"
    proc = _run([ffmpeg, "-y", "-i", str(p), "-filter_complex", filt,
                 "-map", "[v]", "-map", "[a]", str(out)])
    return _ok(output=str(out), factor=f)


@register(
    name="video_scale",
    description="Cambiar la resolución de un video (si solo se da una dimensión se mantiene la proporción)",
    tier="pro",
    timeout=900,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "width": {"type": "integer", "description": "Ancho en píxeles (0 = automático)"},
            "height": {"type": "integer", "description": "Alto en píxeles (0 = automático)"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path", "width", "height"],
    },
)
def video_scale(path: str, width: int, height: int, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    if not width and not height:
        raise ToolError("Indicá width o height (o ambos)")
    p = _resolve(path)
    _check_exists(p)
    w = width if width else -1
    h = height if height else -1
    out = _out_path(p, "_scaled.mp4", output)
    proc = _run([ffmpeg, "-y", "-i", str(p),
                 "-vf", f"scale={w}:{h}", str(out)])
    return _ok(output=str(out), width=width, height=height)


@register(
    name="video_thumbnail",
    description="Generar una imagen (frame) de un video en el segundo indicado",
    tier="pro",
    timeout=300,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "at_sec": {"type": "number", "description": "Segundo del que tomar el frame"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path"],
    },
)
def video_thumbnail(path: str, at_sec: float = 0, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    if at_sec < 0:
        raise ToolError("at_sec no puede ser negativo")
    p = _resolve(path)
    _check_exists(p)
    out = _out_path(p, "_thumb.jpg", output)
    proc = _run([ffmpeg, "-y", "-ss", str(at_sec), "-i", str(p),
                 "-frames:v", "1", "-q:v", "2", str(out)])
    return _ok(output=str(out), at_sec=at_sec)


@register(
    name="video_make_gif",
    description="Crear un GIF animado a partir de un segmento del video",
    tier="pro",
    timeout=900,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "start": {"type": "string", "description": "Inicio (opcional), ej. '5' o '00:00:05'"},
            "end": {"type": "string", "description": "Fin (opcional), ej. '12' o '00:00:12'"},
            "width": {"type": "integer", "description": "Ancho del GIF (alto proporcional)"},
            "fps": {"type": "integer", "description": "Cuadros por segundo del GIF"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path"],
    },
)
def video_make_gif(path: str, start: str = "", end: str = "",
                   width: int = 480, fps: int = 10, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    p = _resolve(path)
    _check_exists(p)
    if not (10 <= width <= 1920):
        raise ToolError("width debe estar entre 10 y 1920")
    if not (1 <= fps <= 30):
        raise ToolError("fps debe estar entre 1 y 30")
    out = _out_path(p, ".gif", output)

    cmd = [ffmpeg, "-y"]
    if start:
        cmd += ["-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-i", str(p), "-vf",
            f"fps={fps},scale={width}:-1:flags=lanczos", "-loop", "0", str(out)]
    proc = _run(cmd)
    return _ok(output=str(out), width=width, fps=fps)


@register(
    name="video_convert",
    description="Convertir un video a otro formato (mp4, webm, mkv, mov) con calidad ajustable",
    tier="pro",
    timeout=1800,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del video"},
            "format": {"type": "string", "enum": ["mp4", "webm", "mkv", "mov"],
                       "description": "Formato de salida"},
            "crf": {"type": "integer", "description": "Calidad 0-51 (18 bueno, 23 normal, 28 comprimido)"},
            "output": {"type": "string", "description": "Ruta de salida (opcional)"},
        },
        "required": ["path", "format"],
    },
)
def video_convert(path: str, format: str = "mp4", crf: int = 23, output: str = "") -> str:
    ffmpeg, _ = _ensure_ffmpeg()
    if not (0 <= int(crf) <= 51):
        raise ToolError("crf debe estar entre 0 y 51")
    codecs = {
        "mp4": ("libx264", "aac"),
        "webm": ("libvpx-vp9", "libopus"),
        "mkv": ("libx264", "aac"),
        "mov": ("libx264", "aac"),
    }
    vcodec, acodec = codecs[format]
    p = _resolve(path)
    _check_exists(p)
    out = _out_path(p, f".{format}", output)
    proc = _run([ffmpeg, "-y", "-i", str(p),
                 "-c:v", vcodec, "-crf", str(crf), "-c:a", acodec, str(out)])
    return _ok(output=str(out), format=format, crf=crf)