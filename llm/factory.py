import logging

from .base import BaseLLM
from .mistral import MistralProvider
from .openai import OpenAIProvider
from .tiered import TieredProvider

logger = logging.getLogger("xens.llm.factory")

_PROVIDER_MAP = {
    "mistral": MistralProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenAIProvider,
}

def create_provider(config: dict) -> BaseLLM:
    providers: dict[str, BaseLLM] = {}
    llm_cfg = config.get("llm", {})

    for name, cls in _PROVIDER_MAP.items():
        provider_cfg = llm_cfg.get(name, {})
        api_key = provider_cfg.get("api_key") or (config.get("api_key") if name == "mistral" else "")
        if not api_key:
            continue

        try:
            p = cls(config)
            providers[name] = p
            logger.info("Loaded provider: %s", name)
        except Exception as e:
            logger.warning("Failed to load provider '%s': %s", name, e)

    if not providers:
        if config.get("api_key"):
            providers["mistral"] = MistralProvider(config)
            logger.info("Loaded default provider: mistral")
        else:
            raise RuntimeError("No API key configured for any provider")

    logger.info("Using TieredProvider with %d provider(s): %s", len(providers), ", ".join(providers))
    return TieredProvider(providers)
