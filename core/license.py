"""
core/license.py — Serial-key licensing (offline, HMAC-signed).

Key format (legible for humans):
    AINSLUP-<TIER>-<DAYS>-<HWID8>-<SIG12>[-<NAME>]
Examples:
    AINSLUP-PRO-3650-3F9A2C1B-9c4b2f1e7766-MARIA
    AINSLUP-PREMIUM-0-00000000-8a3b1c0d5e6f   (lifetime, any machine -> binds on activation)

Legacy XENS- keys are still accepted (same secret, prefix-aware verify).

Security notes:
    - Signature is HMAC-SHA256 over "AINSLUP.TIER.DAYS.HWID" truncated to 48 bits.
      Enough to stop casual forgery for a controlled market; for high-stakes sales
      pair with an online validation endpoint (server returns signed confirmation).
    - HWID "00000000" = unbound: the first machine that activates binds the key.
    - Expiry (DAYS) is checked against the local clock (offline limitation).
"""
import hashlib, hmac, json, os, time, logging
from pathlib import Path

try:
    from ..core.config import config
except ImportError:  # standalone use (e.g. scripts/make_license.py)
    from core.config import config

logger = logging.getLogger("xens.license")

# ---------------------------------------------------------------------------
# Secret resolution: env var > user config > shipped default.
# The shipped default is a placeholder: publish your own in production config
# (config.json -> "license": {"secret": "..."}) so issued keys match them.
# ---------------------------------------------------------------------------
_DEFAULT_SECRET = "xens-prod-2026-secret-7f3a"
_SECRET = (
    os.environ.get("XENS_LICENSE_SECRET")
    or (config.get("license", {}) or {}).get("secret", "")
    or _DEFAULT_SECRET
)

_STATE_PATH = Path.home() / ".ainslup" / "license.json"
STATE_DIR = _STATE_PATH.parent

TIERS = ("FREE", "LITE", "PRO", "PREMIUM")
_TIER_TO_SYSTEM = {"FREE": "free", "LITE": "lite", "PRO": "pro", "PREMIUM": "premium"}
UNBOUND_HWID = "00000000"

# Default license server: the Ainslup Supabase Edge Function. Used as a fallback
# when no server is configured explicitly, so online activation works out of the
# box. Override with env XENS_LICENSE_SERVER / XENS_SERVER_URL, config
# "server": {"url": ...}, or the CLI command /server <url>.
DEFAULT_SERVER_URL = "https://tzlbgoydgptlhspzdhfu.supabase.co/functions/v1/license"


def get_server_url() -> str:
    """License server URL, EXPLICIT configuration only (no default).

    Priority: env XENS_LICENSE_SERVER > env XENS_SERVER_URL > config server.url.
    Returns "" when unset, so callers can decide between online/offline flow.
    """
    for key in ("XENS_LICENSE_SERVER", "XENS_SERVER_URL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return ((config.get("server", {}) or {}).get("url", "") or "").strip()


def get_server_url_with_default() -> str:
    """Like get_server_url(), but falls back to the shipped default endpoint.

    Staging: AINSLUP_EDGE_URL (o AINSLUP_ENV=staging) apunta al proyecto
    de staging sin tocar código.
    """
    env = (os.environ.get("AINSLUP_EDGE_URL") or "").strip()
    if env:
        return env.rstrip("/")
    if (os.environ.get("AINSLUP_ENV") or "").strip().lower() == "staging":
        return "https://mwqkfeyttegxhfvcsjcm.supabase.co/functions/v1/license"
    return get_server_url() or DEFAULT_SERVER_URL


def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def get_hwid() -> str:
    """Stable hardware fingerprint (8 hex chars). MachineGuid-based on Windows."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        val, _ = winreg.QueryValueEx(k, "MachineGuid")
        winreg.CloseKey(k)
        fp = hashlib.sha256((val or "").encode("utf-8")).hexdigest()
    except Exception:
        import uuid
        fp = hashlib.sha256(str(uuid.getnode()).encode("utf-8")).hexdigest()
    return fp[:8]


SERIAL_PREFIX = "AINSLUP"
SERIAL_PREFIXES = ("AINSLUP", "XENS")  # XENS- legacy aceptado


def parse_serial(raw: str) -> dict:
    """Validate a serial and return its payload. Never raises for bad input."""
    try:
        parts = raw.strip().upper().split("-")
        if len(parts) < 5 or parts[0] not in SERIAL_PREFIXES:
            return {"valid": False, "error": f"Must start with {SERIAL_PREFIX}-... (looks like: {SERIAL_PREFIX}-PRO-3650-<hwid>-<code>)"}
        prefix = parts[0]
        tier, days_s, hwid, sig = parts[1], parts[2], parts[3], parts[4]
        name = "-".join(parts[5:]) if len(parts) > 5 else ""
        if tier not in TIERS:
            return {"valid": False, "error": f"Unknown tier '{tier}'. Use {', '.join(TIERS)}."}
        if not days_s.isdigit():
            return {"valid": False, "error": "DAY count must be a number (0 = lifetime)."}
        if len(hwid) != 8 or not all(c in "0123456789ABCDEF" for c in hwid):
            return {"valid": False, "error": "HWID must be 8 hex chars (00000000 = works on any machine)."}
        if len(sig) != 12 or not all(c in "0123456789abcdefABCDEF" for c in sig):
            return {"valid": False, "error": "Signature must be 12 hex chars."}
        payload = f"{prefix}.{tier}.{days_s}.{hwid}"
        expected = _sign(payload)
        if not hmac.compare_digest(expected, sig.lower()):
            return {"valid": False, "error": "Invalid signature — key was not issued by us (or secret mismatch)."}
        return {
            "valid": True,
            "tier": tier,
            "days": int(days_s),
            "hwid": hwid,
            "name": name,
            "payload": payload,
            "key": raw.strip().upper(),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def issue_serial(tier="PRO", days=365, hwid="00000000", name="") -> str:
    """Generate a serial key (admin side). hwid '00000000' => unbound, binds on activation."""
    tier = tier.upper()
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}")
    days = int(days)
    hwid = (hwid or UNBOUND_HWID).upper()
    if len(hwid) != 8:
        raise ValueError("hwid must be 8 hex chars or '00000000'")
    payload = f"{SERIAL_PREFIX}.{tier}.{days}.{hwid}"
    sig = _sign(payload)
    key = f"{SERIAL_PREFIX}-{tier}-{days}-{hwid}-{sig}"
    if name:
        safe = "".join(c for c in name.upper() if c.isalnum() or c == " ").replace(" ", "_")
        if safe:
            key += f"-{safe}"
    return key


def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to read license state: {e}")
    return {}


def _save_state(state: dict):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to write license state: {e}")


def _cfg_unlocked() -> bool:
    return bool((config.get("license", {}) or {}).get("unlocked", False))


def _trial_limit() -> int:
    lc = config.get("license", {}) or {}
    try:
        return max(1, int(lc.get("trial_limit", 300)))
    except Exception:
        return 300


def activate(raw_key: str) -> dict:
    """Activate with a serial. Binds machine if key is unbound. Returns result dict."""
    parsed = parse_serial(raw_key)
    if not parsed["valid"]:
        return {"success": False, "error": parsed.get("error", "Invalid key"), "status": "invalid"}
    hwid = get_hwid()
    key_hwid = parsed["hwid"]
    if key_hwid != UNBOUND_HWID and key_hwid != hwid:
        return {
            "success": False,
            "error": f"Key is bound to another machine (hwid {key_hwid}). Contact the seller.",
            "status": "mismatch",
        }
    days = parsed["days"]
    expires_at = None if days == 0 else int(time.time()) + days * 86400
    state = {
        "key": parsed["key"],
        "tier": parsed["tier"],
        "name": parsed.get("name", ""),
        "hwid": hwid,
        "activated_at": int(time.time()),
        "expires_at": expires_at,
        "days": days,
    }
    _save_state(state)
    logger.info(f"License activated: {parsed['tier']} ({days}d) on hwid {hwid}")
    return {"success": True, "tier": parsed["tier"].lower(), "days": days, "status": "activated"}


def deactivate():
    try:
        if _STATE_PATH.exists():
            _STATE_PATH.unlink()
    except Exception as e:
        logger.warning(f"Failed to remove license state: {e}")


def activate_online(raw_serial: str, server_url: str = "") -> dict:
    """Codex-style online activation: the SERVER validates the serial and returns a token.

    The client never stores your Mistral key — the backend calls the model for it.
    """
    import httpx
    url = (server_url or get_server_url_with_default()).rstrip("/")
    if not url:
        return {"success": False, "error": "No license server configured. Set one with /server <url>.", "status": "no_server"}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{url}/api/activate", json={"serial": raw_serial.strip()})
    except Exception as e:
        hint = ""
        if ".supabase.co" in url:
            hint = " (check that the Supabase project exists and the 'license' Edge Function is deployed)"
        return {"success": False, "error": f"Cannot reach license server ({url}): {e}{hint}", "status": "unreachable"}
    if r.status_code >= 400:
        try:
            err = r.json().get("error") or r.text[:300]
        except Exception:
            err = r.text[:300]
        return {"success": False, "error": f"Server ({r.status_code}): {err}", "status": "rejected"}
    try:
        data = r.json()
        if not isinstance(data, dict):
            return {"success": False, "error": f"Server returned an invalid response: {r.text[:300]}", "status": "rejected"}
    except Exception:
        return {"success": False, "error": f"Server returned non-JSON response: {r.text[:300]}", "status": "rejected"}
    token = data.get("token")
    if not token:
        return {"success": False, "error": "Server returned no token.", "status": "rejected"}
    state = {
        "mode": "online",
        "token": token,
        "tier": (data.get("tier") or "FREE").upper(),
        "server_url": url,
        "expires_at": data.get("expires_at"),
        "activated_at": int(time.time()),
    }
    _save_state(state)
    logger.info(f"Online license activated via {url} (tier {state['tier']})")
    return {"success": True, "tier": state["tier"].lower(), "status": "activated", "online": True}


def provision_free_online(server_url: str = "") -> dict:
    """Cero-config para el consumidor: obtiene la licencia Free lifetime de
    esta máquina (creada en el servidor si no existe) y la guarda.

    No pide serial ni API keys. Best-effort: si no hay internet, devuelve
    el estado actual (trial local) sin romper el arranque.
    """
    import httpx
    url = (server_url or get_server_url_with_default()).rstrip("/")
    if not url:
        return {"success": False, "error": "No license server configured.", "status": "no_server"}
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(f"{url}/api/provision-free", json={"machine_id": get_hwid()})
    except Exception as e:
        return {"success": False, "error": f"Cannot reach license server: {e}", "status": "unreachable"}
    if r.status_code >= 400:
        try:
            err = r.json().get("error") or r.text[:200]
        except Exception:
            err = r.text[:200]
        return {"success": False, "error": f"Server ({r.status_code}): {err}", "status": "rejected"}
    try:
        data = r.json()
    except Exception:
        return {"success": False, "error": "Server returned non-JSON response.", "status": "rejected"}
    token = data.get("token")
    if not token:
        return {"success": False, "error": "Server returned no token.", "status": "rejected"}
    state = {
        "mode": "online",
        "token": token,
        "tier": (data.get("tier") or "FREE").upper(),
        "server_url": url,
        "expires_at": data.get("expires_at"),
        "activated_at": int(time.time()),
        "free_provisioned": True,
    }
    _save_state(state)
    logger.info(f"Free license provisioned via {url}")
    return {"success": True, "tier": state["tier"].lower(), "status": "activated", "online": True}


def ensure_free_license() -> dict:
    """Si no hay licencia ni desbloqueo, auto-activa el Free online.

    Llamar una vez al arrancar. Nunca bloquea ni pide nada al usuario.
    """
    st = get_state()
    if st.get("status") in ("licensed", "unlocked"):
        return {"success": True, "status": st["status"]}
    if _cfg_unlocked():
        return {"success": True, "status": "unlocked"}
    return provision_free_online()


def get_state() -> dict:
    """Full license state, always safe to serialize/send to UI."""
    state = _load_state()
    mode = state.get("mode", "offline")
    activated = bool(state.get("key") or state.get("token"))
    lic_cfg = config.get("license", {}) or {}
    result = {
        "mode": mode,
        "activated": activated,
        "tier": None,
        "key": None,
        "name": state.get("name", ""),
        "hwid": get_hwid(),
        "expires_at": state.get("expires_at"),
        "days_left": None,
        "expired": False,
        "status": "unlicensed",
        "trial_used": int(state.get("trial_used", 0)),
        "trial_limit": _trial_limit(),
        "unlocked": bool(lic_cfg.get("unlocked", False)),
        "online": mode == "online",
        "server_url": state.get("server_url", "") or get_server_url(),
        "token": state.get("token"),
    }
    expires = state.get("expires_at")
    if mode == "online" and state.get("token"):
        result["tier"] = _TIER_TO_SYSTEM.get(state.get("tier", "FREE"), "free")
        if expires:
            result["days_left"] = max(0, int((expires - time.time()) / 86400))
            if time.time() > expires:
                result["expired"] = True
                result["status"] = "expired"
            else:
                result["status"] = "licensed"
        else:
            result["status"] = "licensed"
    elif activated:  # offline serial
        result["tier"] = _TIER_TO_SYSTEM.get(state.get("tier", "FREE"), "free")
        result["key"] = state.get("key")
        if expires:
            result["days_left"] = max(0, int((expires - time.time()) / 86400))
            if time.time() > expires:
                result["expired"] = True
                result["status"] = "expired"
            else:
                result["status"] = "licensed"
        else:
            result["status"] = "licensed"
    elif result["unlocked"]:
        result["status"] = "unlocked"
        result["tier"] = "free"
        result["days_left"] = None
    else:
        result["status"] = "trial" if result["trial_used"] < result["trial_limit"] else "locked"
    return result


def record_trial_use():
    """Count one interaction while in trial mode."""
    state = _load_state()
    if state.get("key") or state.get("token"):
        return
    if _cfg_unlocked():
        return
    used = int(state.get("trial_used", 0)) + 1
    state["trial_used"] = used
    _save_state(state)


def effective_tier() -> str:
    """Tier the registry should run with, driven by the license (unless unlocked/dev)."""
    st = get_state()
    if st["status"] in ("licensed", "unlocked"):
        return st.get("tier") or "free"
    return "free"


def gate_status() -> dict:
    """Should chat be allowed? Returns {"allowed": bool, "reason": str, "state": {...}}."""
    st = get_state()
    if st["status"] in ("licensed", "unlocked"):
        return {"allowed": True, "reason": st["status"], "state": st}
    if st["status"] == "trial":
        return {"allowed": True, "reason": "trial", "state": st}
    return {"allowed": False, "reason": st["status"], "state": st}


def format_status_line() -> str:
    st = get_state()
    prefix = "online " if st["online"] else ""
    if st["status"] == "licensed":
        if st.get("days_left") is None:
            return f"{prefix}{st['tier']} (lifetime)"
        return f"{prefix}{st['tier']} ({st['days_left']}d left)"
    if st["status"] == "unlocked":
        return "dev/unlocked"
    if st["status"] == "expired":
        return f"{prefix}expired ({st['tier']})"
    if st["status"] == "locked":
        return f"LOCKED — trial {st['trial_used']}/{st['trial_limit']} used"
    return f"trial {st['trial_used']}/{st['trial_limit']}"