import json, logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tier")

CONFIG_DIR = Path.home() / ".xens"
TIER_FILE = CONFIG_DIR / "tier_config.json"

DEFAULT_CONFIG = {
    "free": {
        "models": [
            {"provider": "mistral", "model": "mistral-small-2506"}
        ],
        "daily_limit": 300,
    },
    "pro": {
        "models": [
            {"provider": "mistral", "model": "mistral-small-2506"},
            {"provider": "openai", "model": "gpt-4o"},
        ],
        "daily_limit": 3000,
    },
    "premium": {
        "models": [
            {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
            {"provider": "openrouter", "model": "google/gemini-2.0-flash-001"},
            {"provider": "openrouter", "model": "deepseek/deepseek-r1"},
        ],
        "daily_limit": 10000,
    },
}

class TierConfig:
    def __init__(self):
        self._data = {}
        self._source = "default"
        self.load()

    def load(self, path: Optional[Path] = None):
        path = path or TIER_FILE
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("tier config must be a JSON object")
                self._data = data
                self._source = str(path)
                logger.info("Loaded tier config from %s", path)
                return
            except Exception:
                logger.exception("Failed to load tier config from %s", path)
        self._data = DEFAULT_CONFIG
        self._source = "defaults"
        TIER_FILE.parent.mkdir(parents=True, exist_ok=True)
        # No sobrescribir un archivo existente (pero corrupto) con los defaults:
        # el usuario pierde su configuración. Solo escribir si no existía.
        if not path.exists():
            TIER_FILE.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            logger.info("Wrote default tier config to %s", TIER_FILE)

    def load_from_url(self, url: str) -> str:
        import httpx
        try:
            resp = httpx.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("tier config must be a JSON object")
            self._data = data
            self._source = url
            TIER_FILE.parent.mkdir(parents=True, exist_ok=True)
            TIER_FILE.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            logger.info("Tier config synced from %s", url)
            return f"Tier config synced from {url} ({len(self._data)} tiers)"
        except:
            logger.exception("Failed to sync tier config from %s", url)
            return f"Error syncing tier config from {url}"

    def get_tier(self, tier: str) -> dict:
        return self._data.get(tier, self._data.get("free", {}))

    def get_models(self, tier: str) -> list:
        return self.get_tier(tier).get("models", [])

    def get_daily_limit(self, tier: str) -> int:
        return self.get_tier(tier).get("daily_limit", 999999)

    @property
    def tiers(self) -> list[str]:
        return [t for t in ("free", "pro", "premium") if t in self._data]

    @property
    def source(self) -> str:
        return self._source

    def validate(self) -> list[str]:
        errors = []
        for tier in self._data:
            if tier in ("__comment__", "__usage__"):
                continue
            models = self._data[tier].get("models", [])
            if not models:
                errors.append(f"Tier '{tier}' has no models")
            for m in models:
                if "provider" not in m:
                    errors.append(f"Model in tier '{tier}' missing 'provider'")
                if "model" not in m:
                    errors.append(f"Model in tier '{tier}' missing 'model'")
        return errors


tier_config = TierConfig()
