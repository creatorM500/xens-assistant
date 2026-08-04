from __future__ import annotations
import asyncio, json, logging
from typing import AsyncIterator

from ..core.utils import get_http_client
from .base import BaseLLM, Message, LLMResult

logger = logging.getLogger("xens.llm.mistral")

MISTRAL_API = "https://api.mistral.ai/v1/chat/completions"


class MistralProvider(BaseLLM):
    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {}).get("mistral", {})
        self._api_key = llm_cfg.get("api_key") or config.get("api_key", "")
        self._model = llm_cfg.get("model", config.get("model", "mistral-large-latest"))
        self._base_url = llm_cfg.get("base_url", MISTRAL_API)

    @staticmethod
    def _serialize(messages: list[Message]) -> list[dict]:
        serialized = []
        for m in messages:
            entry = {"role": m.role}
            if m.tool_calls:
                entry["content"] = None
                entry["tool_calls"] = m.tool_calls
            else:
                entry["content"] = m.content if isinstance(m.content, str) else str(m.content)
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
                if m.name:
                    entry["name"] = m.name
            serialized.append(entry)
        return serialized

    async def chat(self, messages: list[Message], tools: list = None, **kwargs) -> LLMResult:
        payload = {
            "model": kwargs.get("model", self._model),
            "messages": self._serialize(messages),
            "max_tokens": kwargs.get("max_tokens", 8192),
            "temperature": kwargs.get("temperature", 0.7),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        client = get_http_client()
        resp = None
        for attempt in range(3):
            resp = await client.post(self._base_url, headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }, json=payload)
            data = resp.json()

            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/3)")
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200 or "choices" not in data:
                err = data.get("error", {}).get("message", str(data))
                raise RuntimeError(f"Mistral API error ({resp.status_code}): {err}")
            break
        else:
            raise RuntimeError(f"Mistral API error: rate limited after 3 retries")

        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        tool_calls = []
        raw_tc = msg.get("tool_calls")
        if raw_tc:
            for tc in raw_tc:
                tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                })
        return LLMResult(content=content, tool_calls=tool_calls, usage=data.get("usage"), model=self._model)

    async def chat_stream(self, messages: list[Message], tools: list = None, **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": kwargs.get("model", self._model),
            "messages": self._serialize(messages),
            "max_tokens": kwargs.get("max_tokens", 8192),
            "temperature": kwargs.get("temperature", 0.7),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        client = get_http_client()
        for attempt in range(3):
            resp = await client.post(self._base_url, headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }, json=payload)

            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/3)")
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                body = await resp.aread()
                try:
                    err = json.loads(body).get("error", {}).get("message", body.decode(errors="replace"))
                except:
                    err = body.decode(errors="replace")[:200]
                raise RuntimeError(f"Mistral API error ({resp.status_code}): {err}")
            break

        async with client.stream("POST", self._base_url, headers={
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }, json=payload) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4
