from .registry import register
"""
browser.py — Chrome DevTools Protocol (CDP) automation.
Navigate, click, type, screenshot, extract text via Chrome's remote debugging port.
Requires Chrome with --remote-debugging-port=9222 (auto-launched if needed).
Ported from Omni browser_automation.py with cleanup and JSON returns.
"""
import asyncio, base64, json, logging, os, platform, socket, subprocess, tempfile, time
from typing import Optional

logger = logging.getLogger("xens.tools.browser")

CHROME_DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))

try:
    import websockets
    HAS_WS = True
except ImportError:
    HAS_WS = False


def _default_chrome_path() -> str:
    if platform.system() == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    elif platform.system() == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return "/usr/bin/google-chrome"

CHROME_PATH = os.environ.get("CHROME_PATH", _default_chrome_path())


async def _cdp_send(ws, method, params=None):
    msg = {"id": int(time.time() * 1000), "method": method, "params": params or {}}
    await ws.send(json.dumps(msg))
    async for raw in ws:
        resp = json.loads(raw)
        if resp.get("id") == msg["id"]:
            return resp.get("result", {})


async def _connect():
    try:
        ws = await websockets.connect(f"ws://127.0.0.1:{CHROME_DEBUG_PORT}/devtools/browser")
        resp = await _cdp_send(ws, "Target.getTargets")
        targets = resp.get("targetInfos", [])
        page = next((t for t in targets if t["type"] == "page"), targets[0] if targets else None)
        if not page:
            await ws.close()
            return None
        resp2 = await _cdp_send(ws, "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})
        session_id = resp2.get("sessionId")
        if not session_id:
            await ws.close()
            return None
        return ws, session_id
    except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
        return None


async def _send(ws, session_id, method, params=None):
    msg = {"id": int(time.time() * 1000), "method": method, "params": params or {}, "sessionId": session_id}
    await ws.send(json.dumps(msg))
    async for raw in ws:
        resp = json.loads(raw)
        if resp.get("id") == msg["id"]:
            return resp.get("result", {})


def _ensure_chrome():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", CHROME_DEBUG_PORT))
        s.close()
        return True
    except ConnectionRefusedError:
        pass
    finally:
        s.close()
    try:
        user_data = tempfile.mkdtemp(suffix="_chrome_debug")
        subprocess.Popen(
            [CHROME_PATH, f"--remote-debugging-port={CHROME_DEBUG_PORT}",
             f"--user-data-dir={user_data}", "--no-first-run"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        return True
    except Exception:
        return False


@register(name="browser_navigate", description="Navigate Chrome to a URL via CDP.", tier="free")
async def browser_navigate(url: str) -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed (pip install websockets)", "success": False})
    conn = await _connect()
    if not conn:
        if not _ensure_chrome():
            return json.dumps({"error": "Failed to connect to Chrome. Make sure Chrome is open with --remote-debugging-port=9222", "success": False})
        conn = await _connect()
        if not conn:
            return json.dumps({"error": "Failed to connect to Chrome", "success": False})
    ws, sid = conn
    try:
        await _send(ws, sid, "Page.navigate", {"url": url})
        return json.dumps({"success": True, "action": "navigate", "url": url})
    finally:
        await ws.close()


@register(name="browser_get_title", description="Get the title of the active Chrome tab.", tier="free")
async def browser_get_title() -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        result = await _send(ws, sid, "Runtime.evaluate", {"expression": "document.title"})
        title = result.get("result", {}).get("value", "")
        return json.dumps({"success": True, "title": title})
    finally:
        await ws.close()


@register(name="browser_get_url", description="Get the URL of the active Chrome tab.", tier="free")
async def browser_get_url() -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        result = await _send(ws, sid, "Runtime.evaluate", {"expression": "window.location.href"})
        url = result.get("result", {}).get("value", "")
        return json.dumps({"success": True, "url": url})
    finally:
        await ws.close()


@register(name="browser_get_text", description="Extract text from the page using a CSS selector.", tier="free")
async def browser_get_text(selector: str = "body") -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        result = await _send(ws, sid, "Runtime.evaluate", {
            "expression": f"""(() => {{
                const el = document.querySelector('{selector}');
                return el ? el.innerText.substring(0, 5000) : '';
            }})()""",
        })
        text = result.get("result", {}).get("value", "")
        return json.dumps({"success": True, "text": text})
    finally:
        await ws.close()


@register(name="browser_click", description="Click an element on the page by CSS selector.", tier="free")
async def browser_click(selector: str) -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        result = await _send(ws, sid, "Runtime.evaluate", {
            "expression": f"""(() => {{
                const el = document.querySelector('{selector}');
                if (!el) return 'Element not found: {selector}';
                el.click();
                return 'OK';
            }})()""",
        })
        status = result.get("result", {}).get("value", "OK")
        return json.dumps({"success": status == "OK", "result": status, "selector": selector})
    finally:
        await ws.close()


@register(name="browser_type", description="Type text into an input field by CSS selector.", tier="free")
async def browser_type(selector: str, text: str) -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        safe_text = text.replace("'", "\\'").replace("\n", "\\n")
        result = await _send(ws, sid, "Runtime.evaluate", {
            "expression": f"""(() => {{
                const el = document.querySelector('{selector}');
                if (!el) return 'Element not found: {selector}';
                el.value = '{safe_text}';
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return 'OK';
            }})()""",
        })
        status = result.get("result", {}).get("value", "OK")
        return json.dumps({"success": status == "OK", "result": status, "selector": selector})
    finally:
        await ws.close()


@register(name="browser_screenshot", description="Capture screenshot of the active Chrome tab.", tier="free")
async def browser_screenshot() -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        result = await _send(ws, sid, "Page.captureScreenshot", {"format": "png"})
        data = result.get("data", "")
        if not data:
            return json.dumps({"error": "Failed to capture screenshot", "success": False})
        path = os.path.join(tempfile.gettempdir(), "xens_chrome_screenshot.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return json.dumps({"success": True, "path": path})
    finally:
        await ws.close()


@register(name="browser_list_tabs", description="List open Chrome tabs.", tier="free")
async def browser_list_tabs() -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        resp = await _send(ws, sid, "Target.getTargets")
        pages = [t for t in resp.get("targetInfos", []) if t["type"] == "page"]
        tabs = [{"id": p["targetId"][:8], "title": p.get("title", "")[:60], "url": p.get("url", "")[:100]} for p in pages]
        return json.dumps({"success": True, "count": len(tabs), "tabs": tabs})
    finally:
        await ws.close()


@register(name="browser_search", description="Search for text in the current page.", tier="free")
async def browser_search(text: str) -> str:
    if not HAS_WS:
        return json.dumps({"error": "websockets not installed", "success": False})
    conn = await _connect()
    if not conn:
        return json.dumps({"error": "Chrome not connected", "success": False})
    ws, sid = conn
    try:
        safe = text.lower().replace("'", "\\'")
        result = await _send(ws, sid, "Runtime.evaluate", {
            "expression": f"""(() => {{
                const body = document.body.innerText || '';
                const idx = body.toLowerCase().indexOf('{safe}');
                if (idx === -1) return '';
                const start = Math.max(0, idx - 100);
                const end = Math.min(body.length, idx + 200);
                return body.substring(start, end);
            }})()""",
        })
        snippet = result.get("result", {}).get("value", "")
        return json.dumps({"success": True, "found": bool(snippet), "context": snippet})
    finally:
        await ws.close()
