import hashlib, hmac, json, logging, math, os, time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .tier_config import tier_config

logger = logging.getLogger("xens.credits")

CREDITS_DIR = Path.home() / ".xens"
CREDITS_FILE = CREDITS_DIR / "credits.json"

# Multiplicador de costo por modelo: 1 Xens Credit = 1k tokens base-equivalentes
# del modelo más económico (deepseek-chat 1.2x base). La fórmula:
#   credits = (prompt_tokens + 3.5 * completion_tokens) / 1000 * multiplier
# Output pesa 3.5x input en precio real.
MODEL_COSTS = {
    "deepseek-chat": 1.2,
    "deepseek/deepseek-chat": 1.2,
    "mistral-medium-latest": 3.5,
    "mistral-medium": 3.5,
    "mistral-small-2506": 3.5,
    "mistral-small": 3.5,
    "gemini-2.0-flash-001": 4.8,
    "google/gemini-2.0-flash-001": 4.8,
    "gpt-4o-mini": 4.8,
    "deepseek-r1": 8.0,
    "deepseek/deepseek-r1": 8.0,
    "gpt-4o": 12.0,
    "anthropic/claude-sonnet-4": 20.0,
    "anthropic/claude-sonnet-5": 20.0,
    "claude-sonnet-4": 20.0,
    "claude-sonnet-5": 20.0,
    "z-ai/glm-5.2": 2.5,
    "glm-5.2": 2.5,
    "nvidia/nemotron-3-ultra-550b-a55b": 3.0,
    "openai/gpt-oss-20b": 1.0,
    "gpt-oss-20b": 1.0,
    "openai/gpt-oss-120b": 4.0,
    "gpt-oss-120b": 4.0,
    "groq/compound": 2.0,
    "groq/compound-mini": 1.0,
    "qwen": 1.0,
    "llama-3.3-70b": 2.0,
    "mistral-nemo": 1.0,
    "mistralai/mistral-nemo": 1.0,
}

DEFAULT_MULTIPLIER = 3.5

OUTPUT_WEIGHT = 3.5
BASE_TOKENS_PER_CREDIT = 1000


def model_multiplier(model: str) -> float:
    """Multiplicador de costo de un modelo, con match por sufijo para
    tolerar prefijos de proveedor (p.ej. 'anthropic/claude-sonnet-4')."""
    if not model:
        return DEFAULT_MULTIPLIER
    name = model.strip().lower()
    if name in MODEL_COSTS:
        return MODEL_COSTS[name]
    tail = name.rsplit("/", 1)[-1]
    if tail in MODEL_COSTS:
        return MODEL_COSTS[tail]
    for key, mult in MODEL_COSTS.items():
        if key in name:
            return mult
    return DEFAULT_MULTIPLIER


def _month_key() -> str:
    return time.strftime("%Y-%m")


class CreditLedger:
    def __init__(self):
        self._month: str = ""
        self._spent: dict[str, int] = {}
        self._load()

    def _hmac(self, payload: str) -> str:
        try:
            from .license import _SECRET, get_hwid
            secret = _SECRET
            hwid = get_hwid()
        except Exception:
            secret = os.environ.get("XENS_LICENSE_SECRET", "xens-prod-2026-secret-7f3a")
            hwid = "00000000"
        return hmac.new((secret + hwid).encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]

    def _server_url(self) -> str:
        try:
            from .license import get_server_url
            return get_server_url().rstrip("/")
        except Exception:
            return ""

    def _load(self):
        if CREDITS_FILE.exists():
            try:
                with open(CREDITS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                # HMAC tamper check (local only)
                stored_hmac = data.get("hmac", "")
                month = data.get("month", "")
                spent = data.get("spent") if isinstance(data.get("spent"), dict) else {}
                payload = json.dumps({"month": month, "spent": spent}, sort_keys=True)
                if stored_hmac and stored_hmac != self._hmac(payload):
                    logger.warning("Credits file HMAC mismatch — resetting")
                    self._month = month
                    self._spent = {}
                    return
                self._month = month
                self._spent = spent if isinstance(spent, dict) else {}
            except Exception:
                pass

    def _save(self):
        CREDITS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            payload = json.dumps({"month": self._month, "spent": self._spent}, sort_keys=True)
            h = self._hmac(payload)
            tmp = CREDITS_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"month": self._month, "spent": self._spent, "hmac": h}, f, indent=2)
            tmp.replace(CREDITS_FILE)
        except Exception:
            logger.exception("Failed to save credits")

    def _ensure_month(self):
        month = _month_key()
        if self._month != month:
            self._month = month
            self._spent = {}
            self._save()

    def _key(self, tier: str, uid: Optional[str]) -> str:
        return f"{uid}:{tier}" if uid else f"local:{tier}"

    def limit(self, tier: str) -> int:
        return tier_config.get_credits(tier)

    def balance(self, tier: str, uid: Optional[str] = None) -> int:
        self._ensure_month()
        return max(0, self.limit(tier) - self._spent.get(self._key(tier, uid), 0))

    def check(self, tier: str, uid: Optional[str] = None, need: int = 1) -> tuple[bool, int, int, Optional[int]]:
        # Servidor autoritativo solo si responde; si no, manda el ledger
        # local (el producto funciona sin servidor).
        if uid:
            url = self._server_url()
            if url:
                try:
                    import httpx
                    r = httpx.post(f"{url}/api/credits-check", json={"uid": uid, "tier": tier, "need": need}, timeout=8)
                    if r.status_code == 200:
                        d = r.json()
                        return bool(d.get("allowed", True)), int(d.get("remaining", 0)), int(d.get("limit", self.limit(tier))), d.get("reset_seconds", self._seconds_until_reset())
                    logger.warning("Credits server check failed %s %s", r.status_code, r.text[:200])
                except Exception as e:
                    logger.warning("Credits server unreachable, usando ledger local: %s", e)
        return self._check_local(tier, uid, need)

    def _check_local(self, tier: str, uid: Optional[str], need: int) -> tuple[bool, int, int, Optional[int]]:
        self._ensure_month()
        limit = self.limit(tier)
        key = self._key(tier, uid)
        remaining = max(0, limit - self._spent.get(key, 0))
        return remaining >= need, remaining, limit, self._seconds_until_reset()

    def get_usage(self, tier: str, uid: Optional[str] = None) -> tuple[int, int]:
        self._ensure_month()
        key = self._key(tier, uid)
        used = self._spent.get(key, 0)
        return used, self.limit(tier)

    def cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> int:
        """Créditos que cuesta una llamada LLM (tokens reales del provider)."""
        base = (prompt_tokens + OUTPUT_WEIGHT * completion_tokens) / BASE_TOKENS_PER_CREDIT
        return max(1, int(math.ceil(base * model_multiplier(model))))

    def spend(self, tier: str, uid: Optional[str], usage: Optional[dict],
              model: str = "", prompt_tokens: int = 0, completion_tokens: int = 0) -> dict:
        """Descuenta créditos. Si no hay usage (streams) acepta conteo estimado.

        El ledger local SIEMPRE registra (funciona sin servidor); si hay
        uid y servidor, además lo intenta notificar (best effort).
        """
        if uid:
            url = self._server_url()
            if url:
                try:
                    import httpx
                    payload = {"uid": uid, "tier": tier, "model": model, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
                    if usage:
                        payload["usage"] = usage
                    httpx.post(f"{url}/api/credits-spend", json=payload, timeout=8)
                except Exception as e:
                    logger.warning("Credits server spend unreachable, solo local: %s", e)
        self._ensure_month()
        if usage:
            prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        spent_now = self.cost(prompt_tokens, completion_tokens, model)
        key = self._key(tier, uid)
        self._spent[key] = self._spent.get(key, 0) + spent_now
        self._save()
        limit = self.limit(tier)
        return {
            "spent_now": spent_now,
            "used": self._spent[key],
            "limit": limit,
            "remaining": max(0, limit - self._spent[key]),
        }

    def reset(self):
        self._month = ""
        self._spent = {}
        if CREDITS_FILE.exists():
            CREDITS_FILE.unlink()

    def _seconds_until_reset(self) -> int:
        """Segundos hasta el primer día del mes siguiente (hora LOCAL)."""
        now = datetime.now()
        if now.month == 12:
            nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return int((nxt - now).total_seconds())


credits = CreditLedger()