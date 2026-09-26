"""
server/app.py — reference license + LLM-proxy server (Codex-style).

    Endpoints (the contract that Ainslup client llm/remote.py implements):
    POST /api/activate   {"serial"}                      -> {"token","tier","expires_at"}
    GET  /api/me         Bearer token                    -> {"tier","expires_at","online"}
    POST /api/chat       Bearer token {"messages","tools","tier"} -> {"content","tool_calls","model"}

The Mistral/OpenAI API key lives HERE, never in the client. The server can
revoke a serial (blocklist) to stop paying users instantly.

Run (needs your Mistral key):
    python server/app.py --port 8900
    (MISTRAL_API_KEY is read from env or from ~/.ainslup/config.json)
"""
import argparse, base64, hashlib, hmac, json, logging, os, secrets, time
from pathlib import Path

import aiohttp
from aiohttp import web

from . import store

logger = logging.getLogger("xens.license.server")

HERE = Path(__file__).parent

# -- config -------------------------------------------------------------
def _load_secret() -> str:
    return os.environ.get("XENS_SERVER_SECRET") or "xens-server-ref-2026-change-me"


SECRET = _load_secret()
TOKEN_TTL_DAYS = 30


def _mistral_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    try:
        cfg = json.loads((Path.home() / ".ainslup" / "config.json").read_text(encoding="utf-8"))
        return cfg.get("llm", {}).get("mistral", {}).get("api_key", "") or cfg.get("api_key", "")
    except Exception:
        return ""


MISTRAL_KEY = _mistral_key()
MISTRAL_URL = os.environ.get("XENS_MISTRAL_URL", "https://api.mistral.ai/v1/chat/completions")
MODELS = {
    "FREE": os.environ.get("XENS_MODEL_FREE", "mistral-small-2506"),
    "PRO": os.environ.get("XENS_MODEL_PRO", "mistral-large-latest"),
    "PREMIUM": os.environ.get("XENS_MODEL_PREMIUM", "mistral-large-latest"),
}

# -- token helpers (JWT-like, HMAC) -------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_token(serial: str, tier: str, days_left: int) -> tuple[str, int, str]:
    exp = int(time.time()) + int(days_left or TOKEN_TTL_DAYS) * 86400
    jti = secrets.token_hex(8)
    body = {"sub": serial, "tier": tier, "exp": exp, "iat": int(time.time()), "jti": jti}
    payload = _b64(json.dumps(body).encode())
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{payload}.{sig}", exp, jti


def parse_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(expected, sig):
            return None
        body = json.loads(_unb64(payload))
        if time.time() > body.get("exp", 0):
            return None
        return body
    except Exception:
        return None


def _auth(request) -> tuple[dict, web.Response | None]:
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return None, web.json_response({"error": "Missing Bearer token"}, status=401)
    body = parse_token(hdr[7:])
    if not body:
        return None, web.json_response({"error": "Invalid or expired token"}, status=401)
    if not store.serial_still_valid(body.get("sub", ""), body.get("jti", "")):
        return None, web.json_response({"error": "License revoked by seller"}, status=401)
    return body, None


# -- nocors -------------------------------------------------------------
@web.middleware
async def nocors(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        })
    resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# -- handlers -----------------------------------------------------------
async def h_activate(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Bad JSON"}, status=400)
    serial = (data.get("serial") or "").strip()
    if not serial:
        return web.json_response({"error": "serial required"}, status=400)
    entry = store.redeem_serial(serial)
    if not entry:
        return web.json_response({"error": "Invalid, already used, or revoked serial"}, status=403)
    days_left = entry.get("days", 0)
    token, exp, jti = mint_token(serial.upper(), entry["tier"], days_left)
    store.mark_used(serial.upper(), "first-activator", jti)
    return web.json_response({
        "token": token,
        "tier": entry["tier"].lower(),
        "expires_at": exp,
        "name": entry.get("name", ""),
    })


async def h_me(request):
    body, err = _auth(request)
    if err:
        return err
    return web.json_response({
        "tier": body.get("tier", "free").lower(),
        "expires_at": body.get("exp", 0),
        "online": True,
    })


async def h_chat(request):
    body, err = _auth(request)
    if err:
        return err
    if not MISTRAL_KEY:
        return web.json_response({"error": "Server has no API key configured"}, status=500)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Bad JSON"}, status=400)

    tier = (payload.get("tier") or body.get("tier") or "free").upper()
    model = MODELS.get(tier, MODELS["FREE"])
    msgs = payload.get("messages", [])
    tools = payload.get("tools") or []

    mistral_payload = {
        "model": model,
        "messages": msgs,
        "temperature": 0.3,
    }
    if tools:
        mistral_payload["tools"] = tools

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
        async with s.post(MISTRAL_URL, json=mistral_payload,
                          headers={"Authorization": f"Bearer {MISTRAL_KEY}"}) as r:
            if r.status >= 400:
                text = (await r.text())[:500]
                logger.error("Mistral error %s: %s", r.status, text)
                return web.json_response({"error": f"Model error {r.status}: {text}"}, status=502)
            out = await r.json()

    msg = (out.get("choices") or [{}])[0].get("message", {})
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls") or []
    usage = out.get("usage")
    return web.json_response({
        "content": content,
        "tool_calls": tool_calls,
        "model": model,
        "usage": usage,
        "tier": tier.lower(),
    })


async def h_health(request):
    return web.json_response({"ok": True, "time": int(time.time())})


def main():
    ap = argparse.ArgumentParser(description="Ainslup reference license server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8900)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not MISTRAL_KEY:
        logger.warning("No API key found (MISTRAL_API_KEY env or ~/.ainslup/config.json). Chat proxy will fail.")

    app = web.Application(middlewares=[nocors])
    app.router.add_post("/api/activate", h_activate)
    app.router.add_get("/api/me", h_me)
    app.router.add_post("/api/chat", h_chat)
    app.router.add_get("/api/health", h_health)

    logger.info(f"Ainslup license server on http://{args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()