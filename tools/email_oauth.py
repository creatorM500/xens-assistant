import json, logging, time, base64
from urllib.parse import urlencode
from .registry import register

logger = logging.getLogger("xens.tools.email_oauth")

# Gmail OAuth - requiere GOOGLE_CLIENT_ID/SECRET en env o config
# Para MVP, solo estructura + storage Supabase, flujo manual via browser

def _supabase_url():
    try:
        from ..core.config import config
        return (config.get("supabase", {}) or {}).get("url", "")
    except: return ""

def _supabase_headers():
    try:
        from ..core.config import config
        key = (config.get("supabase", {}) or {}).get("anon_key") or (config.get("supabase", {}) or {}).get("service_key", "")
        if not key:
            return {}
        return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    except: return {}

@register(name="email_connect_gmail", description="Start Gmail OAuth flow. Returns auth URL to open in browser.", parameters={"type": "object", "properties": {"redirect_uri": {"type": "string", "description": "OAuth redirect URI, e.g. http://localhost:18000/oauth/callback"}}, "required": []}, tier="pro")
def email_connect_gmail(redirect_uri: str = "http://localhost:18000/oauth/callback") -> str:
    try:
        from ..core.config import config
        cid = config.get("google", {}).get("client_id") or __import__("os").environ.get("GOOGLE_CLIENT_ID", "")
        if not cid:
            return json.dumps({"error": "Google OAuth not configured. Set google.client_id in config or GOOGLE_CLIENT_ID env.", "success": False})
        params = {
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
            "access_type": "offline",
            "prompt": "consent",
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        return json.dumps({"success": True, "auth_url": url, "redirect_uri": redirect_uri, "instructions": "Open auth_url in browser, then use email_finish_gmail with the code"})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

@register(name="email_finish_gmail", description="Finish Gmail OAuth with code from redirect. Stores tokens.", parameters={"type": "object", "properties": {"code": {"type": "string"}, "redirect_uri": {"type": "string"}}, "required": ["code"]}, tier="pro")
def email_finish_gmail(code: str, redirect_uri: str = "http://localhost:18000/oauth/callback") -> str:
    try:
        from ..core.config import config
        import httpx
        cid = config.get("google", {}).get("client_id") or __import__("os").environ.get("GOOGLE_CLIENT_ID", "")
        sec = config.get("google", {}).get("client_secret") or __import__("os").environ.get("GOOGLE_CLIENT_SECRET", "")
        if not cid or not sec:
            return json.dumps({"error": "Missing client_id/secret", "success": False})
        data = {
            "code": code,
            "client_id": cid,
            "client_secret": sec,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        r = httpx.post("https://oauth2.googleapis.com/token", data=data, timeout=15)
        j = r.json()
        if "access_token" not in j:
            return json.dumps({"error": f"Token exchange failed: {j}", "success": False})
        # guardar en supabase
        try:
            from ..core.credits import credits as _c
            # obtener uid del contexto si hay
            from ..core.llm import charge_ctx
            ctx = charge_ctx.get()
            uid = (ctx or {}).get("uid") or "local"
        except: uid = "local"
        # intentar guardar via supabase REST
        try:
            import httpx as _hx
            url = _supabase_url()
            headers = _supabase_headers()
            if url and headers:
                payload = {"uid": uid, "provider": "gmail", "access_token": j["access_token"], "refresh_token": j.get("refresh_token", ""), "expiry": None, "email": ""}
                _hx.post(f"{url}/rest/v1/email_tokens", headers={**headers, "Prefer": "resolution=merge-duplicates"}, json=payload, timeout=10)
        except Exception as e:
            logger.warning("supabase save failed: %s", e)
        return json.dumps({"success": True, "email": j.get("email", ""), "scope": j.get("scope", "")})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

@register(name="email_list_gmail", description="List recent Gmail messages (requires connect).", parameters={"type": "object", "properties": {"max_results": {"type": "integer"}}, "required": []}, tier="pro")
def email_list_gmail(max_results: int = 5) -> str:
    return json.dumps({"success": False, "error": "Use email_connect_gmail first. Listing requires valid OAuth token (coming soon)."})
