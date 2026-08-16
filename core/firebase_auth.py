"""firebase_auth.py — Verificación de ID tokens de Firebase (JWT RS256).

No requiere service account: valida contra las claves públicas de Firebase
(https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com)
con cache de 1h. Los claims del token definen la cuenta y su plan
(los custom claims de Firebase llegan en el top-level del token).

Uso:
    account = await firebase_auth.verify(token)
    -> {"uid", "email", "name", "tier", ...} o None si es inválido

La autenticación queda desactivada (None) si no hay project_id configurado.
"""
import asyncio, json, logging, time
from typing import Optional

import jwt

logger = logging.getLogger("xens.auth")

_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
_CERTS_TTL = 3600  # 1 hora de cache de claves públicas


class FirebaseAuth:
    def __init__(self, project_id: str):
        self._project_id = (project_id or "").strip()
        self._certs: dict = {}
        self._certs_fetched = 0.0
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._project_id)

    async def _get_certs(self) -> dict:
        if self._certs and time.time() - self._certs_fetched < _CERTS_TTL:
            return self._certs
        async with self._lock:
            if self._certs and time.time() - self._certs_fetched < _CERTS_TTL:
                return self._certs
            try:
                from .utils import get_http_client
                r = await get_http_client().get(_CERTS_URL, timeout=15)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data:
                    self._certs = data
                    self._certs_fetched = time.time()
            except Exception as e:
                logger.warning("No se pudieron renovar las claves de Firebase: %s", e)
            return self._certs

    async def verify(self, token: Optional[str]) -> Optional[dict]:
        """Valida un ID token y devuelve sus claims, o None si es inválido."""
        if not self.enabled or not token or not isinstance(token, str):
            return None
        try:
            header = jwt.get_unverified_header(token)
        except Exception:
            return None
        if header.get("alg") != "RS256":
            return None
        certs = await self._get_certs()
        pem = certs.get(header.get("kid"))
        if not pem:
            return None
        try:
            claims = jwt.decode(
                token,
                pem,
                algorithms=["RS256"],
                audience=self._project_id,
                issuer=f"https://securetoken.google.com/{self._project_id}",
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.PyJWTError as e:
            logger.debug("Token inválido: %s", e)
            return None
        if not claims.get("uid"):
            return None
        return claims

    async def account_from_authorization(self, auth_header: Optional[str]) -> Optional[dict]:
        """Extrae y valida el Bearer token de un header Authorization."""
        if not auth_header:
            return None
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return await self.verify(token.strip())


def build_auth() -> "FirebaseAuth":
    """Crea la instancia según la configuración (core/config.py)."""
    try:
        from .config import config
        project_id = (config.get("firebase", {}) or {}).get("project_id", "")
    except Exception:
        project_id = ""
    auth = FirebaseAuth(project_id)
    if auth.enabled:
        logger.info("Firebase Auth activo (project: %s)", project_id)
    return auth


firebase_auth = build_auth()