from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class Message:
    role: str
    content: str | list[dict]
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


@dataclass
class LLMResult:
    content: str
    tool_calls: list = field(default_factory=list)
    usage: Optional[dict] = None
    model: str = ""

    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLM(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message], tools: list = None, **kwargs) -> LLMResult:
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[Message], tools: list = None, **kwargs) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        ...

    async def get_embedding(self, text: str) -> list[float] | None:
        return None
