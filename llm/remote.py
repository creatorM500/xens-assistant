"""
llm/remote.py — RemoteProvider: pipe Ainslup LLM calls through your OWN backend.

Codex-style protection: the Mistral/OpenAI key lives server-side, never in the
client. The client sends the message history + tool schemas; the backend calls
the model and returns content + tool_calls. Tool EXECUTION stays local.

HTTP contract implemented by any backend (Supabase Edge Function, Python
server, whatever):
    POST {server}/api/chat      body: {"messages": [...], "tools": [...], "tier": "free"}
                                header: Authorization: Bearer <token>
                                -> 200 {"content": str, "tool_calls": [...], "model": str}
                                -> 401  token invalid/expired/revoked
                                -> 4xx  {"error": "..."}
    POST {server}/api/activate  body: {"serial": "..."}
                                -> 200 {"token": str, "tier": "pro", "expires_at": int}
    GET  {server}/api/me        header: Authorization: Bearer <token>
                                -> 200 {"tier": "pro", "email": str, "expires_at": int}

Message JSON follows the OpenAI schema: {role, content, tool_calls?, tool_call_id?, name?}.
"""
import json, logging
from typing import AsyncIterator

from .base import BaseLLM, Message, LLMResult

logger = logging.getLogger("xens.llm.remote")


def _serialize_messages(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        d = {"role": m.role, "content": m.content}
        if m.tool_calls:
            d["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        if m.name:
            d["name"] = m.name
        out.append(d)
    return out


class RemoteProvider(BaseLLM):
    def __init__(self, server_url: str, token: str, model: str = "remote"):
        self._url = server_url.rstrip("/")
        self._token = token
        self._model = model
        self._timeout = 180

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _post(self, path: str, payload: dict) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(f"{self._url}{path}", json=payload, headers=self._headers())
        except Exception as e:
            raise RuntimeError(f"Cannot reach license server ({self._url}): {e}")
        if r.status_code == 401:
            raise PermissionError("License token invalid, expired or revoked (401). Run /activate again.")
        if r.status_code >= 400:
            try:
                err = r.json().get("error") or r.text[:300]
            except Exception:
                err = r.text[:300]
            raise RuntimeError(f"Server error {r.status_code}: {err}")
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"Server returned non-JSON ({r.status_code}): {r.text[:200]}")

    async def chat(self, messages: list[Message], tools: list = None, **kwargs) -> LLMResult:
        payload = {
            "messages": _serialize_messages(messages),
            "tools": tools or [],
            "tier": kwargs.get("tier", "free"),
            "stream": False,
            "xens_stream": False,
            "xens_model": kwargs.get("xens_model") or kwargs.get("alias") or "auto",
        }
        data = await self._post("/api/chat", payload)
        return LLMResult(
            content=data.get("content", "") or "",
            tool_calls=data.get("tool_calls") or [],
            usage=data.get("usage"),
            model=data.get("model", self._model),
        )

    async def chat_stream(self, messages: list[Message], tools: list = None, **kwargs) -> AsyncIterator[str]:
        import httpx, json as _json
        payload = {
            "messages": _serialize_messages(messages),
            "tools": tools or [],
            "tier": kwargs.get("tier", "free"),
            "stream": True,
            "xens_model": kwargs.get("xens_model") or kwargs.get("alias") or "auto",
        }
        # try true streaming, fallback to buffered chat
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                async with c.stream("POST", f"{self._url}/api/chat", json=payload, headers=self._headers()) as r:
                    if r.status_code == 401:
                        raise PermissionError("License token invalid (401)")
                    if r.status_code >= 400:
                        # fallback to non-stream
                        raise RuntimeError(f"stream status {r.status_code}")
                    ctype = r.headers.get("content-type","")
                    if "text/event-stream" not in ctype and "text/plain" not in ctype:
                        # not streaming, fallback
                        raise RuntimeError("not event-stream")
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = _json.loads(data)
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                            # tool_calls streaming ignored for now
                        except Exception:
                            continue
                    return
        except Exception as e:
            logger.debug("Remote stream fallback: %s", e)
        # fallback buffered
        result = await self.chat(messages, tools=tools, **kwargs)
        if result.content:
            # yield word by word to keep perceived streaming
            for w in result.content.split(" "):
                yield w + " "
                # tiny yield to event loop
                import asyncio
                await asyncio.sleep(0.02)

    async def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def get_embedding(self, text: str):
        return None