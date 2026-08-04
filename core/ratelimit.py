import json, time, logging
from pathlib import Path
from typing import Optional

from .tier_config import tier_config

logger = logging.getLogger("xens.ratelimit")

USAGE_DIR = Path.home() / ".xens"
USAGE_FILE = USAGE_DIR / "usage.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class RateLimiter:
    def __init__(self):
        self._day: str = ""
        self._counts: dict[str, int] = {}
        self._load()

    def _load(self):
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE) as f:
                    data = json.load(f)
                self._day = data.get("day", "")
                self._counts = data.get("counts", {})
            except:
                pass

    def _save(self):
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(USAGE_FILE, "w") as f:
                json.dump({"day": self._day, "counts": self._counts}, f, indent=2)
        except:
            logger.exception("Failed to save usage")

    def _ensure_day(self):
        today = _today()
        if self._day != today:
            self._day = today
            self._counts = {}
            self._save()

    def check(self, tier: str = "free") -> tuple[bool, int, int, Optional[int]]:
        self._ensure_day()
        limit = tier_config.get_daily_limit(tier)
        used = self._counts.get(tier, 0)
        remaining = max(0, limit - used)
        reset_seconds = self._seconds_until_reset()
        allowed = used < limit
        return allowed, remaining, limit, reset_seconds

    def record(self, tier: str = "free"):
        self._ensure_day()
        self._counts[tier] = self._counts.get(tier, 0) + 1
        self._save()

    def get_usage(self, tier: str = "free") -> tuple[int, int]:
        self._ensure_day()
        used = self._counts.get(tier, 0)
        limit = tier_config.get_daily_limit(tier)
        return used, limit

    def reset(self):
        self._day = ""
        self._counts = {}
        if USAGE_FILE.exists():
            USAGE_FILE.unlink()

    def _seconds_until_reset(self) -> int:
        now = time.time()
        tomorrow = int(now // 86400 + 1) * 86400
        return int(tomorrow - now)


ratelimiter = RateLimiter()
