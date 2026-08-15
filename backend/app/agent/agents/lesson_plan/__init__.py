"""教学设计 Agent V2 动态工具化。

- 双层结构：稳定教学内核（下游依赖）+ 动态展示目录（AI 按课程与教师指令维护）。
- 多轮 Agent Loop：意图识别 → 计划 → 工具调用（结果回喂）→ QA → 返修（≤3 轮）。
- 流式执行时间线：工具/思考/QA/返修事件实时推送；执行摘要可审计，不展示隐藏思维链。
"""

from app.agent.agents.lesson_plan import agents, builder, intents, qa, runtime, tools  # noqa: F401
from app.agent.agents.lesson_plan.agents import AGENT_BY_KEY  # noqa: F401
from app.agent.agents.lesson_plan.builder import LessonPlanBuilder  # noqa: F401
from app.agent.agents.lesson_plan.qa import validate_lesson_plan  # noqa: F401
from app.agent.agents.lesson_plan.runtime import LessonPlanAgentRuntime  # noqa: F401
from app.schemas.lesson_plan import LessonPlanContentV2  # noqa: F401

__all__ = [
    "LessonPlanAgentRuntime",
    "LessonPlanBuilder",
    "validate_lesson_plan",
    "LessonPlanContentV2",
]
