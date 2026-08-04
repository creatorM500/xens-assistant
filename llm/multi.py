from __future__ import annotations
import asyncio, logging, time, threading
from typing import Any, AsyncIterator, Optional

from .base import BaseLLM, Message, LLMResult

logger = logging.getLogger("xens.llm.multi")


class MultiProvider(BaseLLM):
    def __init__(self, providers: list[BaseLLM], fallback_delay: float = 0.5, health_ttl: float = 60.0):
        self._providers = providers
        self._fallback_delay = fallback_delay
        self._health_ttl = health_ttl
        self._cooldown: dict[int, float] = {}
        self._lock = threading.Lock()
        self._last_provider: Optional[BaseLLM] = None

    def _available(self, idx: int) -> bool:
        with self._lock:
            if idx not in self._cooldown:
                return True
            return time.time() - self._cooldown[idx] > self._health_ttl

    def _mark_unhealthy(self, idx: int):
        with self._lock:
            self._cooldown[idx] = time.time()
        logger.warning("Provider %d (%s) unhealthy, cooling down %.0fs", idx, type(self._providers[idx]).__name__, self._health_ttl)

    async def chat(self, messages: list[Message], tools: list = None, **kwargs) -> LLMResult:
        last_error = None
        for idx, provider in enumerate(self._providers):
            if not self._available(idx):
                continue
            try:
                result = await provider.chat(messages, tools=tools, **kwargs)
                self._last_provider = provider
                return result
            except Exception as e:
                last_error = e
                logger.warning("Provider %d (%s): %s", idx, type(provider).__name__, e)
                self._mark_unhealthy(idx)
                if idx < len(self._providers) - 1:
                    await asyncio.sleep(self._fallback_delay)
        raise last_error or RuntimeError("No providers available")

    async def chat_stream(self, messages: list[Message], tools: list = None, **kwargs) -> AsyncIterator[str]:
        last_error = None
        for idx, provider in enumerate(self._providers):
            if not self._available(idx):
                continue
            try:
                self._last_provider = provider
                async for chunk in provider.chat_stream(messages, tools=tools, **kwargs):
                    yield chunk
                return
            except Exception as e:
                last_error = e
                logger.warning("Provider %d (%s) stream: %s", idx, type(provider).__name__, e)
                self._mark_unhealthy(idx)
                if idx < len(self._providers) - 1:
                    await asyncio.sleep(self._fallback_delay)
        if last_error:
            yield f"\n[All providers failed: {last_error}]"
        else:
            yield "\n[No providers available]"

    async def count_tokens(self, text: str) -> int:
        if self._providers:
            return await self._providers[0].count_tokens(text)
        return 0

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        for idx, provider in enumerate(self._providers):
            if not self._available(idx):
                continue
            try:
                return await provider.get_embedding(text)
            except:
                self._mark_unhealthy(idx)
        return None

    def get_provider_status(self) -> list[dict]:
        return [
            {"index": i, "name": type(p).__name__, "available": self._available(i)}
            for i, p in enumerate(self._providers)
        ]
