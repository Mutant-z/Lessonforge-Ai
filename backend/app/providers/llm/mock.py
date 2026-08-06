from app.providers.llm.base import LLMProvider, T


class MockProvider(LLMProvider):
    """Deterministic provider marker; agents supply schema-valid fixtures for local operation."""

    name = "mock"

    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        raise NotImplementedError("Mock 内容由领域 Agent 的确定性生成器提供")

    async def stream_decision(self, system: str, prompt: str, schema: type[T]):
        # Mock 路径不走 LLM 流：pipeline 直接调用确定性 decide()，并合成 thinking 增量。
        raise NotImplementedError("Mock 模式使用确定性 decide()，不提供流式决策")

    async def stream_text(self, system: str, prompt: str):
        marker = "DISPLAY_REPLY:"
        content = prompt.split(marker, 1)[1].strip() if marker in prompt else "教学意图已更新，请核对右侧理解。"
        for index in range(0, len(content), 6):
            yield content[index:index + 6]

    async def test_connection(self) -> tuple[bool, str]:
        return True, "Mock Provider 测试成功（模拟模式）"
