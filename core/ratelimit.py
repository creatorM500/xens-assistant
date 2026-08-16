import json, time, logging
from datetime import datetime, timedelta
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
                with open(USAGE_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                counts = data.get("counts")
                self._day = data.get("day", "")
                self._counts = counts if isinstance(counts, dict) else {}
            except:
                pass

    def _save(self):
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(USAGE_FILE, "w", encoding="utf-8") as f:
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
        """Segundos hasta la medianoche LOCAL (misma frontera que _today)."""
        now = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((midnight - now).total_seconds())


ratelimiter = RateLimiter()
