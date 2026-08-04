import os, json
from pathlib import Path

CONFIG_DIR = Path.home() / ".xens"
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
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                stored = json.load(f)
                for k, v in stored.items():
                    if k == "llm" and isinstance(v, dict):
                        cfg["llm"].update(v)
                    else:
                        cfg[k] = v
        except:
            pass
    # env var overrides
    env_key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not cfg.get("api_key") and env_key:
        cfg["api_key"] = env_key
    if not cfg["llm"]["mistral"].get("api_key") and cfg.get("api_key"):
        cfg["llm"]["mistral"]["api_key"] = cfg["api_key"]
    return cfg

def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

config = load()
API_KEY = config.get("api_key") or config["llm"]["mistral"].get("api_key", "")
MODEL = config.get("model", "mistral-large-latest")
PORT = config.get("port", 18000)
USER_NAME = config.get("user_name", "")
MAX_CONTEXT_TOKENS = 28000
