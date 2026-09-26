import os, json
from pathlib import Path

from .paths import DATA_HOME  # noqa: F401  (ejecuta migración ~/.xens -> ~/.ainslup)

CONFIG_DIR = DATA_HOME
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "api_key": "",
            "model": "mistral-small-2506",
    "model_vision": "pixtral-large-latest",
    "model_code": "codestral-latest",
    "theme": "dark",
    "user_name": "",
    "port": 18000,
    "llm": {
        "mistral": {
            "api_key": "",
    "model": "mistral-small-2506",
        },
        "openai": {
            "api_key": "",
            "model": "gpt-4o",
        },
        "openrouter": {
            "api_key": "",
            "base_url": "https://openrouter.ai/api/v1",
        },
    },
}

def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8-sig") as f:
                stored = json.load(f)
                for k, v in stored.items():
                    if k == "llm":
                        if not isinstance(v, dict):
                            continue
                        for provider, pv in v.items():
                            if isinstance(pv, dict) and isinstance(cfg["llm"].get(provider), dict):
                                cfg["llm"][provider].update(pv)
                    else:
                        cfg[k] = v
        except Exception as e:
            print(f"  [config] warning: config.json ignored ({e})")
    # env var overrides
    env_key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not cfg.get("api_key") and env_key:
        cfg["api_key"] = env_key
    mistral_cfg = cfg.get("llm", {}).get("mistral", {})
    if isinstance(mistral_cfg, dict) and not mistral_cfg.get("api_key") and cfg.get("api_key"):
        cfg["llm"]["mistral"]["api_key"] = cfg["api_key"]
    return cfg

def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

config = load()
API_KEY = config.get("api_key") or (config.get("llm", {}).get("mistral") or {}).get("api_key", "")
MODEL = config.get("model", "mistral-large-latest")
PORT = config.get("port", 18000)
USER_NAME = config.get("user_name", "")
MAX_CONTEXT_TOKENS = 28000
