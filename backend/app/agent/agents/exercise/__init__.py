"""课后练习 Agent：意图 → 计划 → 工具循环 → QA 返修 → 发布。

与 task_sheet / lesson_plan 同构的第二代 agentic 流水线：核心循环复用
app/agent/core/loop，领域逻辑（意图/角色/工具/QA）在本包内实现。
"""

from app.agent.agents.exercise.agents import (
    AGENT_BY_KEY, ensure_exercise_agents, exercise_spec, is_mock_provider,
)
from app.agent.agents.exercise.builder import ExerciseBuilder, build_initial_builder, upgrade_builder
from app.agent.agents.exercise.intents import (
    INTENT_AGENT_ALIASES, ExerciseIntentDecision,
    agent_chain_for_intent, infer_exercise_intent,
)
from app.agent.agents.exercise.qa import (
    LlmExerciseQaResult, blocking_issues, exercise_validate_rules,
    fingerprint, issue, llm_qa_system_prompt, normalize_llm_issues,
)
from app.agent.agents.exercise.runtime import ExerciseAgentRuntime

__all__ = [
    "AGENT_BY_KEY", "ensure_exercise_agents", "exercise_spec", "is_mock_provider",
    "ExerciseBuilder", "build_initial_builder", "upgrade_builder",
    "INTENT_AGENT_ALIASES", "ExerciseIntentDecision",
    "agent_chain_for_intent", "infer_exercise_intent",
    "LlmExerciseQaResult", "blocking_issues", "exercise_validate_rules",
    "fingerprint", "issue", "llm_qa_system_prompt", "normalize_llm_issues",
    "ExerciseAgentRuntime",
]
