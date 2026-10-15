import json, logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tier")

CONFIG_DIR = Path.home() / ".ainslup"
TIER_FILE = CONFIG_DIR / "tier_config.json"

# Facturación unificada OpenRouter: todos los alias van por OpenRouter.
# Mistral directo solo queda como respaldo de emergencia en el edge.
XENS_ALIASES = {
    "Flash": {"provider": "openrouter", "model": "mistralai/mistral-nemo", "label": "Flash — rápido", "use": "chat diario"},
    "Core": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "label": "Core — equilibrado", "use": "resumen/instrucciones"},
    "Think": {"provider": "openrouter", "model": "deepseek/deepseek-r1", "label": "Think — razonamiento", "use": "lógica/mates"},
    "Code": {"provider": "openrouter", "model": "qwen/qwen-2.5-coder-32b-instruct", "label": "Code — código", "use": "refactor/debug"},
    "Vision": {"provider": "openrouter", "model": "google/gemini-2.0-flash-001", "label": "Vision — imagen", "use": "pantalla/OCR"},
    "Ultra": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4", "label": "Ultra — frontera", "use": "análisis profundo"},
}
ALIAS_TO_MODEL = {k: v["model"] for k, v in XENS_ALIASES.items()}
ALIAS_PROVIDER = {k: v["provider"] for k, v in XENS_ALIASES.items()}

DEFAULT_CONFIG = {
    "free": {
        "models": [
            {"provider": "pollinations", "model": "nvidia/nemotron-3-ultra"},
            {"alias": "Flash", "provider": "openrouter", "model": "mistralai/mistral-nemo"},
            {"alias": "Core", "provider": "openrouter", "model": "deepseek/deepseek-chat"},
        ],
        "credits": 5000,
    },
    "lite": {
        "models": [
            {"alias": "Flash", "provider": "openrouter", "model": "mistralai/mistral-nemo"},
            {"alias": "Core", "provider": "openrouter", "model": "deepseek/deepseek-chat"},
            {"alias": "Vision", "provider": "openrouter", "model": "google/gemini-2.0-flash-001"},
        ],
        "credits": 15000,
    },
    "pro": {
        "models": [
            {"alias": "Flash", "provider": "openrouter", "model": "mistralai/mistral-nemo"},
            {"alias": "Core", "provider": "openrouter", "model": "deepseek/deepseek-chat"},
            {"alias": "Think", "provider": "openrouter", "model": "deepseek/deepseek-r1"},
            {"alias": "Code", "provider": "openrouter", "model": "qwen/qwen-2.5-coder-32b-instruct"},
            {"alias": "Vision", "provider": "openrouter", "model": "google/gemini-2.0-flash-001"},
        ],
        "credits": 35000,
    },
    "premium": {
        "models": [
            {"alias": "Flash", "provider": "openrouter", "model": "mistralai/mistral-nemo"},
            {"alias": "Core", "provider": "openrouter", "model": "deepseek/deepseek-chat"},
            {"alias": "Think", "provider": "openrouter", "model": "deepseek/deepseek-r1"},
            {"alias": "Code", "provider": "openrouter", "model": "qwen/qwen-2.5-coder-32b-instruct"},
            {"alias": "Vision", "provider": "openrouter", "model": "google/gemini-2.0-flash-001"},
            {"alias": "Ultra", "provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
            {"alias": "Ultra", "provider": "openrouter", "model": "google/gemini-2.0-flash-001", "alt": True},
        ],
        "credits": 125000,
    },
}

class TierConfig:
    def __init__(self):
        self._data = {}
        self._source = "default"
        self.load()

    def load(self, path: Optional[Path] = None):
        path = path or TIER_FILE
        stale = False
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("tier config must be a JSON object")
                # Migración: configs viejas (sin lite o con ids Mistral directos)
                # sombrearían los defaults nuevos. Se reemplazan una vez.
                models_blob = json.dumps(data)
                if "lite" not in data or "mistral-small-2506" in models_blob or "pixtral-large" in models_blob:
                    raise ValueError("stale tier config, migrating to defaults")
                self._data = data
                self._source = str(path)
                logger.info("Loaded tier config from %s", path)
                # Migración aditiva (no destructiva): segundo cerebro gratis
                # (Pollinations) al frente del tier free en configs ya existentes.
                try:
                    if "pollinations" not in models_blob:
                        free_models = self._data.get("free", {}).get("models")
                        if isinstance(free_models, list):
                            free_models.insert(0, {"provider": "pollinations", "model": "nvidia/nemotron-3-ultra"})
                            path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
                            logger.info("Tier config migrada: pollinations al frente de free")
                except Exception:
                    logger.exception("No se pudo migrar tier config con pollinations")
                return
            except Exception as e:
                logger.exception("Failed to load tier config from %s", path)
                stale = "stale tier config" in str(e)
        self._data = DEFAULT_CONFIG
        self._source = "defaults"
        TIER_FILE.parent.mkdir(parents=True, exist_ok=True)
        # No sobrescribir un archivo existente (pero corrupto) con los defaults:
        # el usuario pierde su configuración. Solo escribir si no existía,
        # salvo migración de formato viejo (stale), que sí se reemplaza.
        if not path.exists() or stale:
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

    def resolve_alias(self, alias: str, tier: str = "free") -> dict | None:
        if not alias or alias.lower() == "auto":
            return None
        # En beta los modelos se restringen a la lista del plan Free.
        for m in self.get_models(self.models_tier(tier)):
            if m.get("alias", "").lower() == alias.lower():
                return m
        return None

    def aliases_for_tier(self, tier: str) -> list[str]:
        return [m.get("alias") for m in self.get_models(self.models_tier(tier)) if m.get("alias")]

    # ---- Beta interna: plan superior con modelos del Free ----
    # beta_plan vive en ~/.ainslup/config.json ("beta_plan": "pro"|"" ).
    # Cualquiera puede elegirlo desde Configuración; sirve para probar
    # Ainslup (créditos/tools del plan) sin gastar modelos grandes.
    def get_beta_plan(self) -> str:
        try:
            from .config import CONFIG_FILE
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
                plan = str((data or {}).get("beta_plan") or "").strip().lower()
                if plan in ("free", "lite", "pro", "premium"):
                    return plan
        except Exception:
            pass
        return ""

    def set_beta_plan(self, plan: str) -> str:
        from .config import CONFIG_FILE, load, save
        plan = (plan or "").strip().lower()
        if plan in ("auto", "off", "none"):
            plan = ""
        if plan and plan not in ("free", "lite", "pro", "premium"):
            raise ValueError(f"Invalid beta plan '{plan}'")
        cfg = load()
        if plan:
            cfg["beta_plan"] = plan
        else:
            cfg.pop("beta_plan", None)
        save(cfg)
        logger.info("Beta plan set to '%s'", plan or "off")
        return plan

    def effective_tier(self, tier: str) -> str:
        """Tier real para créditos/tools: beta_plan si está activo."""
        beta = self.get_beta_plan()
        return beta or (tier or "free")

    def models_tier(self, tier: str) -> str:
        """Tier para elegir modelos: siempre 'free' en beta."""
        return "free" if self.get_beta_plan() else (tier or "free")

    def is_beta(self) -> bool:
        return bool(self.get_beta_plan())

    def get_daily_limit(self, tier: str) -> int:
        return self.get_tier(tier).get("daily_limit", 999999)

    def get_credits(self, tier: str) -> int:
        return int(self.get_tier(tier).get("credits", 10000))

    @property
    def tiers(self) -> list[str]:
        return [t for t in ("free", "lite", "pro", "premium") if t in self._data]

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
