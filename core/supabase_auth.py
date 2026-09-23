"""supabase_auth.py — Verifica JWT de Supabase Auth (HS256).

Supabase firma con SUPABASE_JWT_SECRET (HS256, audience 'authenticated').
No requiere RS256 ni certs externos: solo HMAC local.

claims esperados: { sub=uid, email, aud='authenticated', exp, ... }
Uso async igual que firebase_auth:
    acct = await supabase_auth.verify(token) -> {"uid","email","tier"} | None
"""
import logging, os, time
from typing import Optional

import jwt

logger = logging.getLogger("xens.auth")

_JWT_SECRET = ""  # lazy load desde env / config
_JWK_CACHE = {}  # no JWK, solo HS256

def _get_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET:
        return _JWT_SECRET
    # 1) env SUPABASE_JWT_SECRET (supabase dashboard -> project settings -> API -> JWT Secret)
    s = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
    if s:
        _JWT_SECRET = s
        return s
    # 2) config.json supabase.jwt_secret
    try:
        from .config import config
        s = ((config.get("supabase", {}) or {}).get("jwt_secret", "") or "").strip()
        if s:
            _JWT_SECRET = s
            return s
    except Exception:
        pass
    return ""

class SupabaseAuth:
    @property
    def enabled(self) -> bool:
        return bool(_get_secret())

    async def verify(self, token: Optional[str]) -> Optional[dict]:
        if not token or not isinstance(token, str):
            return None
        # 1) intento HS256 local si hay secret
        secret = _get_secret()
        if secret:
            try:
                header = jwt.get_unverified_header(token)
                if header.get("alg") == "HS256":
                    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": True, "verify_aud": False, "verify_iss": False})
                    uid = claims.get("sub") or claims.get("uid")
                    if uid:
                        meta = claims.get("user_metadata") or {}
                        app_meta = claims.get("app_metadata") or {}
                        tier = (app_meta.get("tier") or meta.get("tier") or claims.get("tier") or "free").lower()
                        if tier not in ("free","lite","pro","premium"): tier="free"
                        return {"uid": str(uid), "email": claims.get("email") or meta.get("email") or "", "name": meta.get("name") or meta.get("full_name") or claims.get("email") or str(uid)[:8], "tier": tier, "claims": claims}
            except Exception as e:
                logger.debug("HS256 verify falló, probando API: %s", e)
        # 2) fallback: validar contra Supabase Auth API (no necesita JWT_SECRET)
        try:
            from .config import config
            url = ((config.get("supabase", {}) or {}).get("url") or "https://tzlbgoydgptlhspzdhfu.supabase.co").rstrip("/")
            anon = ((config.get("supabase", {}) or {}).get("anon_key") or os.environ.get("SUPABASE_ANON_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR6bGJnb3lkZ3B0bGhzcHpkaGZ1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM4MTM5NTEsImV4cCI6MjA5OTM4OTk1MX0.euj51hQUQUkWLZHNV_DkX1d0c9qxp9gz5J_AVmjkm30")
            import httpx
            r = await httpx.AsyncClient().get(f"{url}/auth/v1/user", headers={"apikey": anon, "Authorization": f"Bearer {token}"}, timeout=8)
            if r.status_code != 200:
                return None
            data = r.json()
            uid = data.get("id") or data.get("sub")
            if not uid:
                return None
            meta = data.get("user_metadata") or {}
            app_meta = data.get("app_metadata") or {}
            tier = (app_meta.get("tier") or meta.get("tier") or "free").lower()
            if tier not in ("free","lite","pro","premium"): tier="free"
            return {"uid": str(uid), "email": data.get("email") or meta.get("email") or "", "name": meta.get("name") or meta.get("full_name") or data.get("email") or str(uid)[:8], "tier": tier, "claims": data}
        except Exception as e:
            logger.debug("Supabase API verify falló: %s", e)
            return None

    async def account_from_authorization(self, auth_header: Optional[str]) -> Optional[dict]:
        if not auth_header:
            return None
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return await self.verify(token.strip())

def build_auth() -> "SupabaseAuth":
    auth = SupabaseAuth()
    if auth.enabled:
        logger.info("Supabase Auth activo (HS256)")
    else:
        logger.info("Supabase Auth desactivado (sin SUPABASE_JWT_SECRET / supabase.jwt_secret)")
    return auth

supabase_auth = build_auth()
# Compat alias para código que aún importe firebase_auth
firebase_auth = supabase_auth
