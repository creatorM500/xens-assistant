"""server/store.py — tiny JSON persistence for the reference license server.

Data lives in server/data/ (gitignored). Production: mirror this in Supabase
tables (`serials`, `users`) with RLS. The HTTP contract stays identical.
"""
import json, secrets, time, logging
from copy import deepcopy
from pathlib import Path

logger = logging.getLogger("xens.license.server")

DATA_DIR = Path(__file__).parent / "data"
SERIALS_PATH = DATA_DIR / "serials.json"
USERS_PATH = DATA_DIR / "users.json"


def _load(path: Path, default: dict) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
    return default


def _save(path: Path, data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_serials() -> dict:
    return _load(SERIALS_PATH, {})


def save_serials(data: dict):
    _save(SERIALS_PATH, data)


def load_users() -> dict:
    return _load(USERS_PATH, {})


def save_users(data: dict):
    _save(USERS_PATH, data)


def new_serial(tier: str, days: int, name: str = "", count: int = 1) -> list[str]:
    serials = load_serials()
    codes = []
    for _ in range(max(1, count)):
        code = "AINSLUP-" + "-".join(
            secrets.token_hex(4).upper() for _ in range(4)
        )
        serials[code] = {
            "tier": tier.upper(),
            "days": int(days),
            "name": name,
            "issued": int(time.time()),
            "used_by": None,
            "used_at": None,
            "active": True,
        }
        codes.append(code)
    save_serials(serials)
    return codes


def redeem_serial(code: str) -> dict | None:
    """Validate + mark used. Returns entry or None."""
    code = code.strip().upper()
    serials = load_serials()
    entry = serials.get(code)
    if not entry:
        return None
    if not entry.get("active", True):
        return None
    if entry.get("used_by"):
        return None  # one-time use
    return deepcopy(entry)


def mark_used(code: str, device: str, token_jti: str):
    serials = load_serials()
    entry = serials.get(code)
    if entry:
        entry["used_by"] = device
        entry["used_at"] = int(time.time())
        entry["token_jti"] = token_jti
        save_serials(serials)


def revoke_serial(code: str) -> bool:
    serials = load_serials()
    entry = serials.get(code.upper())
    if entry:
        entry["active"] = False
        save_serials(serials)
        return True
    return False


def serial_still_valid(code: str, jti: str) -> bool:
    """Server-side revocation check for /api/me and /api/chat."""
    serials = load_serials()
    entry = serials.get(code)
    if not entry:
        return False
    if not entry.get("active", True):
        return False
    if entry.get("token_jti") != jti:
        return False
    return True