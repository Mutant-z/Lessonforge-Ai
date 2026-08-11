from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# 流式决策事件：("thought_delta", str) 实时思考文本块 ｜ ("decision_ready", T) 完整决策
DecisionStreamEvent = tuple[str, object]


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

    async def structured_with_image(self, system: str, prompt: str, image_b64: str,
                                    image_media_type: str, schema: type[T]) -> T:
        raise NotImplementedError("该 provider 不支持图像输入")

    @abstractmethod
    async def stream_decision(self, system: str, prompt: str, schema: type[T]) -> AsyncIterator[DecisionStreamEvent]:
        """流式返回结构化决策。

        LLM 以 stream=True 生成 JSON 决策；本方法实时 yield：
        - ("thought_delta", str)：从 JSON 流中增量提取的 thinking 文本（Markdown，供前端打字机）
        - ("decision_ready", T)：流结束并解析/校验后的决策对象
        内容异常时应回退到非流式 structured() 兜底。
        """
        raise NotImplementedError

    @abstractmethod
    async def stream_text(self, system: str, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError
