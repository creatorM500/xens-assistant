import asyncio, logging, time, threading
from typing import Any, AsyncIterator, Optional

from .base import BaseLLM, Message, LLMResult
from ..core.tier_config import tier_config

logger = logging.getLogger("xens.llm.tiered")


class TieredProvider(BaseLLM):
    def __init__(self, providers: dict[str, BaseLLM]):
        self._providers = providers
        self._cooldown: dict[str, float] = {}
        self._cooldown_ttl: dict[str, float] = {}
        self._lock = threading.Lock()
        self._health_ttl = 60.0

    def _available(self, name: str) -> bool:
        with self._lock:
            if name not in self._cooldown:
                return True
            ttl = self._cooldown_ttl.get(name, self._health_ttl)
            return time.time() - self._cooldown[name] > ttl

    def _mark_unhealthy(self, name: str, exc: Exception = None):
        ttl = self._health_ttl
        if exc:
            msg = str(exc).lower()
            if "rate limit" in msg or "429" in msg:
                ttl = 15.0
        with self._lock:
            self._cooldown[name] = time.time()
            self._cooldown_ttl[name] = ttl
        logger.warning("Provider '%s' unhealthy, cooling down %.0fs", name, ttl)

    async def chat(self, messages: list[Message], tools: list = None,
                   tier: str = "free", background: bool = False, models: list = None, **kwargs) -> LLMResult:
        model_entries = models or tier_config.get_models(tier)
        if not model_entries:
            raise RuntimeError(f"No models configured for tier '{tier}'")

        last_error = None
        for entry in model_entries:
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
                if not background:
                    self._mark_unhealthy(provider_name, e)
                if len(models) > 1:
                    await asyncio.sleep(0.5)
        raise last_error or RuntimeError(f"No providers available for tier '{tier}'")

    async def chat_stream(self, messages: list[Message], tools: list = None,
                          tier: str = "free", background: bool = False, models: list = None, **kwargs) -> AsyncIterator[str]:
        model_entries = models or tier_config.get_models(tier)
        if not model_entries:
            yield f"\n[No models configured for tier '{tier}']"
            return

        last_error = None
        for entry in model_entries:
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
                if not background:
                    self._mark_unhealthy(provider_name, e)
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
        for name, p in self._providers.items():
            if self._available(name):
                try:
                    return await p.get_embedding(text)
                except Exception as e:
                    logger.warning("Embedding provider '%s' failed: %s", name, e)
        return None
