from .registry import register
"""
vision.py — Screenshot, OCR, image analysis.
Portable from Xens Omni vision.py with path cleanup and JSON return format.
"""
import json, os, logging, platform, subprocess, tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("xens.tools.vision")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


@register(name="take_screenshot", description="Take a screenshot and save to a file. Optionally specify path.", tier="free")
def take_screenshot(path: str = None) -> str:
    if not path:
        name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = str(Path(tempfile.gettempdir()) / name)
    try:
        if HAS_MSS:
            with mss.mss() as sct:
                sct.shot(output=path)
        elif HAS_PIL:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(path)
        elif platform.system() == "Windows":
            subprocess.run(
                ["powershell", "-Command",
                 f"Add-Type -AssemblyName System.Windows.Forms; "
                 f"$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                 f"$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
                 f"$g = [System.Drawing.Graphics]::FromImage($bmp); "
                 f"$g.CopyFromScreen(0, 0, 0, 0, $b.Size); "
                 f"$bmp.Save('{path}')"],
                capture_output=True, text=True, timeout=10
            )
        else:
            return json.dumps({"error": "No capture method available (pip install mss or Pillow)", "success": False})
        return json.dumps({"success": True, "path": path})
    except Exception as e:
        return json.dumps({"error": f"Screenshot failed: {e}", "success": False})


@register(name="ocr_image", description="Extract text from an image file using OCR (Spanish + English).", tier="free")
def ocr_image(image_path: str) -> str:
    if not HAS_TESSERACT:
        return json.dumps({"error": "OCR not available (pip install pytesseract + tesseract-ocr)", "success": False})
    if not os.path.exists(image_path):
        return json.dumps({"error": f"File not found: {image_path}", "success": False})
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="spa+eng").strip()
        if not text:
            return json.dumps({"success": True, "text": "", "note": "No text detected"})
        if len(text) > 2000:
            text = text[:2000] + "\n[...]"
        return json.dumps({"success": True, "text": text})
    except Exception as e:
        return json.dumps({"error": f"OCR failed: {e}", "success": False})


@register(name="read_screen", description="Take a screenshot and extract all visible text using OCR in one call.", tier="free")
def read_screen() -> str:
    """Screenshot + OCR in one call."""
    tmp = os.path.join(tempfile.gettempdir(), f"_ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    cap = take_screenshot(tmp)
    cap_data = json.loads(cap)
    if not cap_data.get("success"):
        return cap
    result = ocr_image(tmp)
    try:
        os.remove(tmp)
    except Exception:
        pass
    return result


@register(name="describe_image", description="Get image metadata (dimensions, format, size, EXIF) and optional OCR text.", tier="free")
def describe_image(path: str) -> str:
    if not os.path.exists(path):
        return json.dumps({"error": f"File not found: {path}", "success": False})
    info = {"path": path}
    stat = os.stat(path)
    info["size"] = stat.st_size
    info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    if HAS_PIL:
        try:
            img = Image.open(path)
            info["width"] = img.width
            info["height"] = img.height
            info["format"] = img.format
            info["mode"] = img.mode
        except Exception as e:
            info["pil_error"] = str(e)
    if HAS_TESSERACT:
        try:
            ocr_result = json.loads(ocr_image(path))
            if ocr_result.get("success") and ocr_result.get("text"):
                info["detected_text"] = ocr_result["text"][:500]
        except Exception:
            pass
    return json.dumps({"success": True, **info})
