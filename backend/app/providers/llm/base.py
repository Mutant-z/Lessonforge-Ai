from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TypeVar

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

    #: 是否支持原生 function/tool calling（方案 §3.1）。
    supports_native_tools: bool = False

    @abstractmethod
    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        raise NotImplementedError

    async def structured_with_image(self, system: str, prompt: str, image_b64: str,
                                    image_media_type: str, schema: type[T]) -> T:
        raise NotImplementedError("该 provider 不支持图像输入")

    async def structured_with_attachments(
        self,
        system: str,
        prompt: str,
        attachments: list[dict[str, str]],
        schema: type[T],
    ) -> T:
        """Structured request with native image/PDF inputs.

        Providers that understand a multimodal wire protocol override this
        method.  The default keeps older custom providers compatible by using
        the single-image implementation when possible.
        """
        if len(attachments) == 1 and attachments[0].get("mime_type", "").startswith("image/"):
            return await self.structured_with_image(
                system,
                prompt,
                attachments[0].get("data_b64", ""),
                attachments[0].get("mime_type", "image/png"),
                schema,
            )
        raise NotImplementedError("该 provider 不支持多模态附件输入")

    @abstractmethod
    async def stream_decision(self, system: str, prompt: str, schema: type[T]) -> AsyncIterator[DecisionStreamEvent]:
        """流式返回结构化决策。

        LLM 以 stream=True 生成 JSON 决策；本方法实时 yield：
        - ("thought_delta", str)：从 JSON 流中增量提取的 thinking 文本（Markdown，供前端打字机）
        - ("decision_ready", T)：流结束并解析/校验后的决策对象
        内容异常时应回退到非流式 structured() 兜底。
        """
        raise NotImplementedError

    async def native_agent_decision(
        self,
        system: str,
        prompt: str,
        tools: list[dict[str, Any]],
    ) -> "AgentDecision | None":
        """原生 tool calling（方案 §3.1）：模型原生返回工具调用或完成决策。

        返回 None 表示协议不可用/返回协议错误，调用方回退现有结构化 AgentDecision
        协议并发 ``provider.tool_protocol_fallback`` 事件。回退不改变工具执行、QA、
        事件与发布语义。
        """
        raise NotImplementedError("该 provider 不支持原生 tool calling")

    async def native_agent_decision_with_attachments(
        self,
        system: str,
        prompt: str,
        attachments: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> "AgentDecision | None":
        """Native tool call with attachments; default falls back to text-only."""
        return await self.native_agent_decision(system, prompt, tools)

    async def stream_decision_with_attachments(
        self,
        system: str,
        prompt: str,
        attachments: list[dict[str, str]],
        schema: type[T],
    ) -> AsyncIterator[DecisionStreamEvent]:
        """Stream a structured decision with native attachments.

        The default is deliberately finite but valid, allowing older provider
        implementations to keep working while concrete providers add native
        streaming support.
        """
        yield ("decision_ready", await self.structured_with_attachments(system, prompt, attachments, schema))

    @abstractmethod
    async def stream_text(self, system: str, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError
