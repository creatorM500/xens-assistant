import asyncio, logging, time, threading
from typing import Any, AsyncIterator, Optional

from .base import BaseLLM, Message, LLMResult
from ..core.tier_config import tier_config

logger = logging.getLogger("xens.llm.tiered")


class TieredProvider(BaseLLM):
    def __init__(self, providers: dict[str, BaseLLM]):
        self._providers = providers
        self._cooldown: dict[str, float] = {}
        self._lock = threading.Lock()
        self._health_ttl = 60.0

    def _available(self, name: str) -> bool:
        with self._lock:
            if name not in self._cooldown:
                return True
            return time.time() - self._cooldown[name] > self._health_ttl

    def _mark_unhealthy(self, name: str):
        with self._lock:
            self._cooldown[name] = time.time()
        logger.warning("Provider '%s' unhealthy, cooling down %.0fs", name, self._health_ttl)

    async def chat(self, messages: list[Message], tools: list = None,
                   tier: str = "free", **kwargs) -> LLMResult:
        models = tier_config.get_models(tier)
        if not models:
            raise RuntimeError(f"No models configured for tier '{tier}'")

        last_error = None
        for entry in models:
            provider_name = entry.get("provider")
            model_name = entry.get("model")
            provider = self._providers.get(provider_name)
            if not provider or not self._available(provider_name):
                continue
            try:
                result = await provider.chat(messages, tools=tools, model=model_name, **kwargs)
                return result
            except Exception as e:
                last_error = e
                logger.warning("Provider '%s' model '%s': %s", provider_name, model_name, e)
                self._mark_unhealthy(provider_name)
                if len(models) > 1:
                    await asyncio.sleep(0.5)
        raise last_error or RuntimeError(f"No providers available for tier '{tier}'")

    async def chat_stream(self, messages: list[Message], tools: list = None,
                          tier: str = "free", **kwargs) -> AsyncIterator[str]:
        models = tier_config.get_models(tier)
        if not models:
            yield f"\n[No models configured for tier '{tier}']"
            return

        last_error = None
        for entry in models:
            provider_name = entry.get("provider")
            model_name = entry.get("model")
            provider = self._providers.get(provider_name)
            if not provider or not self._available(provider_name):
                continue
            try:
                async for chunk in provider.chat_stream(messages, tools=tools, model=model_name, **kwargs):
                    yield chunk
                return
            except Exception as e:
                last_error = e
                logger.warning("Provider '%s' model '%s' stream: %s", provider_name, model_name, e)
                self._mark_unhealthy(provider_name)
                if len(models) > 1:
                    await asyncio.sleep(0.5)
        if last_error:
            yield f"\n[All providers failed for tier '{tier}': {last_error}]"
        else:
            yield f"\n[No providers available for tier '{tier}']"

    async def count_tokens(self, text: str) -> int:
        for p in self._providers.values():
            return await p.count_tokens(text)
        return 0

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        for p in self._providers.values():
            if self._available(p.__class__.__name__.lower()):
                try:
                    return await p.get_embedding(text)
                except:
                    pass
        return None
