"""通用 Agent 基类：每个 Agent 提供 decide（确定性 Mock）与 build_system_prompt（LLM 路径）。

与 app/agent/agents/base.py 等价但领域无关：允许子类覆盖角色提示词模板。
"""

from abc import ABC, abstractmethod

from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision


class Agent(ABC):
    key: str = ""
    name: str = ""
    role: str = ""
    description: str = ""
    required_artifacts: list[str] = []
    produced_artifacts: list[str] = []
    allowed_tools: list[str] = []

    @abstractmethod
    async def decide(self, tc: ToolContext) -> AgentDecision:
        """确定性决策（Mock 路径）：返回工具调用或完成（含产物数据）。"""

    def build_system_prompt(self, tc: ToolContext, runtime: AgentRuntimeState | None = None) -> str:
        return (
            f"你是 LessonForge AI 的「{self.name}」Agent。\n职责：{self.role}\n"
            "工作方式：一次返回 AgentDecision JSON —— 要么给出一批工具调用（tools），"
            "要么在完成时标记 completed 并给出 output（本次产出的 Artifact 数据）与 summary。\n"
            "规则：\n"
            "· 每次工具调用都要提供合法的 input（符合工具 input_schema）；\n"
            "· 工具失败时根据错误修正入参后重试，不要伪造数据；\n"
            "· 只修改内存中的候选稿（LessonPlanBuilder），绝不直接改写正式 Artifact；\n"
            "· 遵守上下文中的职责边界、锁定路径和质量检查清单，不展示隐藏推理。\n"
        )
