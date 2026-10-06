from __future__ import annotations
import json, logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from ..core.utils import get_http_client
from .base import BaseLLM, Message, LLMResult

logger = logging.getLogger("xens.llm.openai")


class OpenAIProvider(BaseLLM):
    def __init__(self, config: dict, section: str = "openai"):
        llm_cfg = config.get("llm", {}).get(section, {})
        api_key = llm_cfg.get("api_key") or config.get("api_key", "")
        defaults = {"openai": ("https://api.openai.com/v1", "gpt-4o"),
                    "openrouter": ("https://openrouter.ai/api/v1", "deepseek/deepseek-chat")}
        base_url = llm_cfg.get("base_url") or defaults.get(section, defaults["openai"])[0]
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = llm_cfg.get("model") or defaults.get(section, defaults["openai"])[1]
        self._section = section

    def _to_openai(self, msgs: list[Message]) -> list[dict]:
        result = []
        for m in msgs:
            d = {"role": m.role, "content": m.content if isinstance(m.content, str) else str(m.content)}
            if m.tool_calls:
                d["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            result.append(d)
        return result

    def _from_openai(self, choice, usage=None) -> LLMResult:
        msg = choice.message
        content = msg.content or ""
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                })
        u = usage.model_dump() if usage else None
        return LLMResult(content=content, tool_calls=tool_calls, usage=u, model=self._model)

    async def chat(self, messages: list[Message], tools: list = None, **kwargs) -> LLMResult:
        oa_msgs = self._to_openai(messages)
        oa_tools = tools if tools else None
        resp = await self._client.chat.completions.create(
            model=kwargs.get("model", self._model),
            messages=oa_msgs,
            tools=oa_tools,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
        )
        return self._from_openai(resp.choices[0], resp.usage)

    async def chat_stream(self, messages: list[Message], tools: list = None, **kwargs) -> AsyncIterator[str]:
        oa_msgs = self._to_openai(messages)
        oa_tools = tools if tools else None
        stream = await self._client.chat.completions.create(
            model=kwargs.get("model", self._model),
            messages=oa_msgs,
            tools=oa_tools,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4
