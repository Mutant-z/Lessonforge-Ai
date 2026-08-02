from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMProviderError(RuntimeError):
    """A safe, stable provider error that can cross the API boundary."""

    code: str
    user_message: str
    retryable: bool = False
    status_code: int | None = None
    content_type: str = ""
    response_length: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.user_message)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        raise NotImplementedError

    @abstractmethod
    async def stream_text(self, system: str, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError
