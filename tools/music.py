from .registry import register
"""
music.py — Spotify playback control.
OAuth via localhost HTTP server. Tokens stored in ~/.xens/spotify_token.json.
Ported from Xens Omni spotify_control.py with path cleanup and JSON returns.
"""
import asyncio, json, logging, os, threading, time, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.music")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

_DATA_DIR = Path.home() / ".xens"
_TOKEN_PATH = _DATA_DIR / "spotify_token.json"
_CONFIG_PATH = _DATA_DIR / "spotify_config.json"
_CLIENT_ID = "5f0c7c1b2c7a4b9e8b3c1d2e3f4a5b6c"
_CLIENT_SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
_REDIRECT_URI = "http://localhost:8888/callback"
_SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing playlist-read-private user-read-private"

_auth_code = None
_server_instance = None


def _load_token() -> dict:
    try:
        if _TOKEN_PATH.exists():
            return json.loads(_TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_token(tok: dict):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(json.dumps(tok), encoding="utf-8")

def _load_config() -> dict:
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_config(cfg: dict):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

def _refresh_token(tok: dict) -> dict:
    r = requests.post("https://accounts.spotify.com/api/token",
        data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        auth=(_CLIENT_ID, _CLIENT_SECRET))
    if r.status_code == 200:
        new = r.json()
        tok["access_token"] = new["access_token"]
        tok["expires_at"] = time.time() + new.get("expires_in", 3600)
        _save_token(tok)
    return tok

def _get_valid_token() -> str:
    tok = _load_token()
    if not tok:
        return ""
    if time.time() > tok.get("expires_at", 0):
        tok = _refresh_token(tok)
    return tok.get("access_token", "")


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        _auth_code = qs.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        if _auth_code:
            self.wfile.write(b"<h1>Authentication complete</h1><p>You can close this window.</p>")
        else:
            self.wfile.write(b"<h1>Authentication failed</h1>")
        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, *a, **kw):
        pass


# Spotify authenticator DISABLED for now: tool removed from registry to avoid blocking.
# @register(name="authenticate_spotify", description="Authenticate with Spotify via OAuth. Opens browser for login. Times out after 120s if not completed.", tier="free", timeout=150)
async def authenticate_spotify(client_id: str = "", client_secret: str = "") -> str:
    global _CLIENT_ID, _CLIENT_SECRET, _auth_code, _server_instance
    if not HAS_REQUESTS:
        return json.dumps({"error": "requests not installed (pip install requests)", "success": False})
    if client_id:
        _CLIENT_ID = client_id
    if client_secret:
        _CLIENT_SECRET = client_secret
    _save_config({"client_id": _CLIENT_ID, "client_secret": _CLIENT_SECRET})
    import threading
    from http.server import HTTPServer
    _auth_code = None
    try:
        server = HTTPServer(("localhost", 8888), _CallbackHandler)
    except OSError as e:
        return json.dumps({"error": f"Could not bind port 8888 (maybe already in use): {e}", "success": False})
    _server_instance = server
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    auth_url = (f"https://accounts.spotify.com/authorize"
        f"?response_type=code&client_id={_CLIENT_ID}"
        f"&redirect_uri={_REDIRECT_URI}&scope={_SCOPES.replace(' ', '%20')}")
    webbrowser.open(auth_url)
    deadline = time.time() + 120
    while time.time() < deadline:
        if _auth_code:
            break
        await asyncio.sleep(0.3)
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    if not _auth_code:
        return json.dumps({"error": "Authentication cancelled or timed out", "success": False})
    r = requests.post("https://accounts.spotify.com/api/token",
        data={"grant_type": "authorization_code", "code": _auth_code,
              "redirect_uri": _REDIRECT_URI},
        auth=(_CLIENT_ID, _CLIENT_SECRET))
    if r.status_code != 200:
        return json.dumps({"error": f"Token error: {r.text[:200]}", "success": False})
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600)
    _save_token(tok)
    user = _get_user()
    return json.dumps({"success": True, "message": f"Authenticated as {user}", "user": user})


def _get_user() -> str:
    token = _get_valid_token()
    if not token:
        return "?"
    r = requests.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 200:
        return r.json().get("display_name", "?")
    return "?"


def _api(method: str, path: str, data=None) -> dict:
    token = _get_valid_token()
    if not token:
        return {"error": "Spotify not authenticated. Use authenticate_spotify first."}
    url = f"https://api.spotify.com/v1{path}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.request(method, url, headers=headers, json=data, timeout=10)
        if r.status_code == 204:
            return {"ok": True}
        if r.status_code == 401:
            tok = _load_token()
            if tok:
                tok = _refresh_token(tok)
                headers["Authorization"] = f"Bearer {tok['access_token']}"
                r = requests.request(method, url, headers=headers, json=data, timeout=10)
        if r.status_code == 204:
            return {"ok": True}
        if r.status_code >= 400:
            return {"error": r.text[:200]}
        return r.json() if r.text else {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@register(name="spotify_play", description="Play music on Spotify. Optionally specify a track/playlist URI.", tier="free")
def spotify_play(uri: str = "", device_id: str = "") -> str:
    body = {}
    if uri:
        body["context_uri"] = uri if ":" in uri else f"spotify:track:{uri}"
    r = _api("PUT", f"/me/player/play?device_id={device_id}" if device_id else "/me/player/play", body)
    if "error" in r:
        dev = spotify_devices()
        if "No active device" in r.get("error", ""):
            return json.dumps({"error": "No active device found. Open Spotify on a device first.", "devices": json.loads(dev).get("devices", []), "success": False})
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "play", "uri": uri if uri else "current"})


@register(name="spotify_pause", description="Pause Spotify playback.", tier="free")
def spotify_pause() -> str:
    r = _api("PUT", "/me/player/pause")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "pause"})


@register(name="spotify_next", description="Skip to next track on Spotify.", tier="free")
def spotify_next() -> str:
    r = _api("POST", "/me/player/next")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "next"})


@register(name="spotify_previous", description="Go to previous track on Spotify.", tier="free")
def spotify_previous() -> str:
    r = _api("POST", "/me/player/previous")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "previous"})


@register(name="spotify_volume", description="Set Spotify volume (0-100).", tier="free")
def spotify_volume(percent: int) -> str:
    p = max(0, min(100, percent))
    r = _api("PUT", f"/me/player/volume?volume_percent={p}")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "volume", "percent": p})


@register(name="spotify_now_playing", description="Get currently playing track info from Spotify.", tier="free")
def spotify_now_playing() -> str:
    r = _api("GET", "/me/player/currently-playing")
    if "error" in r:
        dev = spotify_devices() if "No active device" in r.get("error", "") else ""
        return json.dumps({"error": r["error"], "success": False})
    if not r or "item" not in r:
        return json.dumps({"success": True, "playing": False})
    item = r["item"]
    return json.dumps({
        "success": True,
        "playing": r.get("is_playing", False),
        "track": item.get("name", "?"),
        "artists": [a["name"] for a in item.get("artists", [])],
        "album": item.get("album", {}).get("name", ""),
        "progress_ms": r.get("progress_ms", 0),
        "duration_ms": item.get("duration_ms", 0),
    })


@register(name="spotify_devices", description="List available Spotify devices.", tier="free")
def spotify_devices() -> str:
    r = _api("GET", "/me/player/devices")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    devices = r.get("devices", [])
    return json.dumps({"success": True, "count": len(devices), "devices": [
        {"name": d["name"], "type": d["type"], "active": d.get("is_active", False)}
        for d in devices
    ]})


@register(name="spotify_search", description="Search Spotify for tracks, albums, or playlists.", tier="free")
def spotify_search(query: str, type: str = "track") -> str:
    r = _api("GET", f"/search?q={query.replace(' ', '%20')}&type={type}&limit=10")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    items = r.get(f"{type}s", {}).get("items", [])
    return json.dumps({
        "success": True,
        "query": query,
        "type": type,
        "count": len(items),
        "results": [
            {"name": item["name"], "artists": [a["name"] for a in item.get("artists", [])],
             "album": item.get("album", {}).get("name", ""), "uri": item["uri"]}
            for item in items[:10]
        ]
    })


@register(name="spotify_shuffle", description="Toggle Spotify shuffle mode.", tier="free")
def spotify_shuffle(active: bool = True) -> str:
    r = _api("PUT", f"/me/player/shuffle?state={'true' if active else 'false'}")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "shuffle", "active": active})


@register(name="spotify_repeat", description="Set Spotify repeat mode: off, track, or context.", tier="free")
def spotify_repeat(mode: str = "context") -> str:
    if mode not in ("off", "track", "context"):
        return json.dumps({"error": "Mode must be: off, track, or context", "success": False})
    r = _api("PUT", f"/me/player/repeat?state={mode}")
    if "error" in r:
        return json.dumps({"error": r["error"], "success": False})
    return json.dumps({"success": True, "action": "repeat", "mode": mode})
