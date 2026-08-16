"""课后练习 Agent V2 流水线测试：Builder / QA 门禁 / 工具 / 意图 / Runtime / 知识摘要。

- Builder 种子：make_exercises 确定性示例 → 三区 40/40/20、总分 100、评分守恒。
- QA 门禁：总分、引用、评分点守恒违规 → blocking。
- 工具：题目修改、删除需要确认令牌。
- 意图：Mock fallback 关键字路由 + LLM 路径脚本 provider。
- Runtime：Mock 全链路 initial 生成 → 发布门禁通过、review_summary 回填。
- 知识摘要：Mock 回退 bounded；LLM 摘要缓存命中跳过。
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.agent.agents.exercise.builder import ExerciseBuilder, build_initial_builder, upgrade_builder
from app.agent.agents.exercise.intents import (
    ExerciseIntentDecision,
    agent_chain_for_intent,
    infer_exercise_intent,
)
from app.agent.agents.exercise.qa import (
    blocking_issues,
    exercise_validate_rules,
    fingerprint,
)
from app.agent.agents.exercise.runtime import ExerciseAgentRuntime
from app.agent.agents.exercise.tools import register_exercise_tools
from app.agent.context import ContextState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.agents.generators import make_exercises
from app.schemas.artifact import ExerciseContent
from app.schemas.blueprint import CourseBlueprintSchema

BP = {
    "course_identity": {"title": "浮力", "subject": "物理", "grade_level": "八年级",
                        "audience": "初二", "duration_minutes": 10, "scenario": "课堂讲解"},
    "learning_analysis": {"prior_knowledge": [], "learner_characteristics": [], "likely_misconceptions": []},
    "objectives": [
        {"id": "OBJ-01", "domain": "knowledge", "behavior": "解释浮力", "condition": "结合情境",
         "criterion": "说明依据", "knowledge_point_ids": ["KP-01"], "activity_ids": ["S1"], "exercise_ids": []},
        {"id": "OBJ-02", "domain": "skill", "behavior": "应用原理", "condition": "给定数据",
         "criterion": "结果正确", "knowledge_point_ids": ["KP-01"], "activity_ids": ["S2"], "exercise_ids": []},
    ],
    "knowledge_points": [{"id": "KP-01", "name": "浮力"}],
    "key_points": ["浮力产生条件"], "difficulty_points": ["原理应用"],
    "teaching_strategy": ["情境导入"],
    "timeline": [
        {"segment_id": "S1", "name": "导入", "start_minute": 0, "end_minute": 3,
         "purpose": "p", "teacher_action": "t", "learner_action": "l", "evidence_of_learning": "e"},
        {"segment_id": "S2", "name": "探究", "start_minute": 3, "end_minute": 10,
         "purpose": "p", "teacher_action": "t", "learner_action": "l", "evidence_of_learning": "e"},
    ],
    "assessment_plan": [{"objective_id": "OBJ-01", "method": "m", "evidence": "e", "criterion": "c"}],
    "terminology": {}, "source_refs": [],
}


@pytest.fixture
def bp() -> CourseBlueprintSchema:
    return CourseBlueprintSchema.model_validate(BP)


@pytest.fixture
def exercise_data(bp) -> dict:
    return make_exercises(bp).model_dump()


# ---------------------------------------------------------------------------
# Builder / 种子
# ---------------------------------------------------------------------------


def test_seed_builder_sections_scores_and_validity(bp, exercise_data):
    builder = ExerciseBuilder(exercise_data)
    sections = builder.sections
    assert [s["id"] for s in sections] == [
        "basic_consolidation", "understanding_application", "transfer_challenge",
    ]
    assert [s["score"] for s in sections] == [40, 40, 20]
    assert builder.paper_settings["total_score"] == 100
    assert builder.validate_content()["ok"] is True


def test_exercise_checkpoint_never_skips_fresh_builder_steps():
    """A restarted process has a fresh Builder, so an old step index is unsafe."""
    from app.services.exercise_pipeline_service import _exercise_checkpoint_resume

    start, restarted = _exercise_checkpoint_resume({
        "step_index": 7,
        "paused_agent": "question_designer",
        "agents_done": ["intent_planner", "context_researcher"],
    })
    assert start == 0
    assert restarted is True

    start, restarted = _exercise_checkpoint_resume({"pending_confirmation": {"token": "ok"}})
    assert start == 0
    assert restarted is False


def test_build_initial_builder_from_blueprint(bp):
    builder = build_initial_builder(BP, task_sheet_raw=None)
    content = builder.to_content()
    assert content["schema_version"] == "2.0"
    assert ExerciseContent.model_validate(content).model_dump() == ExerciseContent.model_validate(content).model_dump()
    assert not blocking_issues(exercise_validate_rules(bp, content))


def test_upgrade_builder_preserves_v2_and_rebuilds_bad(bp, exercise_data):
    builder = upgrade_builder(exercise_data, BP)
    assert builder.to_content() == exercise_data
    bad = copy.deepcopy(exercise_data)
    bad["schema_version"] = "1.0"
    rebuilt = upgrade_builder(bad, BP)
    assert rebuilt.to_content()["schema_version"] == "2.0"
    assert len(rebuilt.sections) == 3


# ---------------------------------------------------------------------------
# QA 门禁
# ---------------------------------------------------------------------------


def test_qa_fresh_seed_passes(bp, exercise_data):
    assert not blocking_issues(exercise_validate_rules(bp, exercise_data))


def test_qa_rejects_total_score_drift(bp, exercise_data):
    data = copy.deepcopy(exercise_data)
    data["paper_settings"]["total_score"] = 90
    issues = exercise_validate_rules(bp, data)
    # total_score≠分区分值之和 → 结构校验失败（integrity critical）或规则门禁（scoring critical），均为阻断
    assert any(item["severity"] == "critical" for item in issues)


def test_qa_rejects_bad_objective_reference(bp, exercise_data):
    data = copy.deepcopy(exercise_data)
    data["sections"][0]["blocks"][0]["objective_ids"] = ["OBJ-404"]
    issues = exercise_validate_rules(bp, data)
    assert any(item["severity"] == "critical" and "OBJ-404" in item["description"] for item in issues)


def test_qa_rejects_rubric_points_drift(bp, exercise_data):
    data = copy.deepcopy(exercise_data)
    question = data["sections"][1]["blocks"][0]["sub_questions"][0]
    question["scoring_points"][0]["points"] += 5
    issues = exercise_validate_rules(bp, data)
    # 评分点之和≠题目分值 → pydantic 结构校验失败（integrity critical）或规则门禁（scoring critical）
    assert any(item["severity"] == "critical" for item in issues)


def test_fingerprint_stable(bp, exercise_data):
    data = copy.deepcopy(exercise_data)
    data["paper_settings"]["total_score"] = 90
    first = fingerprint(exercise_validate_rules(bp, data))
    second = fingerprint(exercise_validate_rules(bp, data))
    assert first == second


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _tool_context(builder: ExerciseBuilder) -> ToolContext:
    register_exercise_tools()
    runtime = SimpleNamespace(
        provider=None, locks=[], intent_plan=None, confirmation_tokens=[],
        knowledge_context={}, source_artifact=None, profile=None,
    )
    ctx = ContextState(blueprint=BP, knowledge={}, user_instruction="", locks=[])
    return ToolContext(ctx=ctx, runtime=runtime, extra={"builder": builder})


def _multiple_choice(question_id: str, score: int = 5) -> dict:
    return {
        "kind": "question",
        "id": question_id,
        "question_type": "multiple_choice",
        "stem": f"多选题 {question_id}",
        "options": [
            {"id": "A", "text": "选项甲"}, {"id": "B", "text": "选项乙"},
            {"id": "C", "text": "选项丙"}, {"id": "D", "text": "选项丁"},
        ],
        "score": score,
        "estimated_minutes": 1.0,
        "objective_ids": ["OBJ-01"],
        "knowledge_point_ids": ["KP-01"],
        "source_refs": ["S1"],
        "difficulty": "basic",
        "cognitive_level": "understand",
        "answer_key": {"correct_option_ids": ["A", "B"], "accepted_answers": [], "reference_answer": ""},
        "analysis": "A、B 分别对应正确概念。",
        "scoring_points": [],
        "answer_space": {"mode": "none", "lines": 0},
        "common_errors": [],
    }


def _set_score(question: dict, score: int) -> None:
    question["score"] = score
    if question.get("scoring_points"):
        first = copy.deepcopy(question["scoring_points"][0])
        first["points"] = score
        question["scoring_points"] = [first]


def _thirty_thirty_five_thirty_five_with_three_multi(exercise_data: dict) -> dict:
    data = copy.deepcopy(exercise_data)
    basic, understanding, transfer = data["sections"]
    basic["score"] = 30
    _set_score(basic["blocks"][0], 15)
    _set_score(basic["blocks"][1], 15)
    understanding["score"] = 35
    group = understanding["blocks"][0]
    _set_score(group["sub_questions"][0], 10)
    _set_score(group["sub_questions"][1], 10)
    group["sub_questions"].extend([
        _multiple_choice("MC-01"), _multiple_choice("MC-02"), _multiple_choice("MC-03"),
    ])
    transfer["score"] = 35
    _set_score(transfer["blocks"][0], 35)
    return ExerciseContent.model_validate(data).model_dump()


def test_tool_update_question_breaks_conservation(bp, exercise_data):
    from app.agent.agents.exercise.tools.check_tools import _exercise_validate_scoring
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    tc = _tool_context(builder)
    question = exercise_data["sections"][0]["blocks"][0]
    result = asyncio.run(execute_tool("exercise_update_question", tc, {
        "question_id": question["id"], "patch": {"score": 30},
    }))
    assert result.ok
    scoring = asyncio.run(_exercise_validate_scoring(tc, SimpleNamespace()))
    assert not scoring.output["passed"]
    assert any(item["dimension"] == "scoring" and item["severity"] == "critical" for item in scoring.output["issues"])


def test_tool_delete_question_requires_token(bp, exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    tc = _tool_context(builder)
    question_id = exercise_data["sections"][0]["blocks"][0]["id"]
    result = asyncio.run(execute_tool("exercise_delete_question", tc, {
        "question_id": question_id, "confirmation_token": None,
    }))
    assert not result.ok
    assert "人工确认" in result.error


def test_tool_delete_question_with_token(bp, exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    tc = _tool_context(builder)
    tc.runtime.confirmation_tokens = ["confirm-test"]
    question_id = exercise_data["sections"][0]["blocks"][0]["id"]
    result = asyncio.run(execute_tool("exercise_delete_question", tc, {
        "question_id": question_id, "confirmation_token": "confirm-test",
    }))
    assert result.ok
    assert question_id not in builder.all_question_ids()


def test_scope_guard_ignores_hallucinated_target_ids(bp, exercise_data):
    """回归：意图识别把"第六题"猜成 q6（文档真实 ID 是 ex_06）时，
    作用域守卫应忽略无效目标，放行真实 ID 的修改，而不是误拦导致死循环。"""
    from app.agent.agents.exercise.tools._common import _scope_guard
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    real_id = exercise_data["sections"][2]["blocks"][0]["id"]
    tc = _tool_context(builder)
    # intent_plan 携带 LLM 编造的 ID（q6 在文档中不存在）
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT", target_question_ids=["q6"], confidence=0.9,
    )
    # 用真实 ID 修改 → 不应被 scope guard 拦截
    result = asyncio.run(execute_tool("exercise_update_question", tc, {
        "question_id": real_id, "patch": {"stem": "已润色分行后的题干"},
    }))
    assert result.ok, result.error
    # 直接调用 _scope_guard 也应放行
    _scope_guard(tc, question_ids=[real_id], section_ids=["transfer_challenge"])


def test_scope_guard_keeps_valid_target_ids(bp, exercise_data):
    """有效目标 ID 仍严格限制修改范围（保留意图约束能力）。"""
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    real_id = exercise_data["sections"][2]["blocks"][0]["id"]
    other_id = exercise_data["sections"][0]["blocks"][0]["id"]
    tc = _tool_context(builder)
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT", target_question_ids=[real_id], confidence=0.9,
    )
    # 修改范围外的题目 → 拒绝
    result = asyncio.run(execute_tool("exercise_update_question", tc, {
        "question_id": other_id, "patch": {"stem": "越权修改"},
    }))
    assert not result.ok
    assert "不属于本轮意图范围" in result.error
    # 范围内的题目 → 放行
    result = asyncio.run(execute_tool("exercise_update_question", tc, {
        "question_id": real_id, "patch": {"stem": "合法修改"},
    }))
    assert result.ok


def test_add_block_idempotent_upsert_keeps_stable_id(bp, exercise_data):
    """回归：重复 add 同一 ID 必须原地覆盖而非改名，保证 update 永远能找到。

    这是"补充多选题到五题"反复失败的根因：LLM 重复 add ex_multi_01 时若被
    改名成 ex_multi_01_2，后续 update ex_multi_01 就找不到（题目不存在）。
    """
    builder = ExerciseBuilder(exercise_data)
    original_count = len(builder.all_question_ids())
    new_block = {
        "kind": "question",
        "id": "ex_multi_01",
        "question_type": "multiple_choice",
        "stem": "第一版题干",
        "options": [
            {"id": "A", "text": "甲"}, {"id": "B", "text": "乙"},
            {"id": "C", "text": "丙"}, {"id": "D", "text": "丁"},
        ],
        "score": 10,
        "estimated_minutes": 2.0,
        "objective_ids": ["OBJ-01"],
        "knowledge_point_ids": ["KP-01"],
        "source_refs": ["S1"],
        "difficulty": "basic",
        "cognitive_level": "understand",
        "answer_key": {"correct_option_ids": ["A", "B"], "accepted_answers": [], "reference_answer": ""},
        "analysis": "分析一",
        "answer_space": {"mode": "none", "lines": 0},
    }
    first = builder.add_block("basic_consolidation", new_block)
    assert first["id"] == "ex_multi_01"
    assert builder.find_question("ex_multi_01")[0] is not None

    # 重复 add 同一 ID（不同分区）→ 原地覆盖，ID 不变，题目数量不增加
    moved = dict(new_block)
    moved["stem"] = "第二版题干（覆盖）"
    second = builder.add_block("understanding_application", moved)
    assert second["id"] == "ex_multi_01", "ID 必须保持稳定"
    assert len(builder.all_question_ids()) == original_count + 1, "题目数量不得因重复 add 增加"
    # ID 在目标分区且内容为最新版
    question, section, group = builder.find_question("ex_multi_01")
    assert question is not None
    assert section.get("id") == "understanding_application"
    assert question["stem"] == "第二版题干（覆盖）"
    # update 用同一 ID 永远能找到
    builder.update_block("ex_multi_01", {"stem": "第三版"})
    assert builder.find_question("ex_multi_01")[0]["stem"] == "第三版"


def test_update_question_supports_group_sub_question(exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    tc = _tool_context(builder)
    sub_question = exercise_data["sections"][1]["blocks"][0]["sub_questions"][0]
    result = asyncio.run(execute_tool("exercise_update_question", tc, {
        "question_id": sub_question["id"], "patch": {"stem": "已更新的题组子题"},
    }))
    assert result.ok, result.error
    assert builder.find_question(sub_question["id"])[0]["stem"] == "已更新的题组子题"


def test_atomic_question_batch_updates_live_source_and_preserves_scores(exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    tc = _tool_context(builder)
    tc.runtime.baseline_content = builder.to_content()
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT",
        operation="ensure_question_type_count",
        question_type="multiple_choice",
        target_count=2,
        current_count=0,
        requested_delta=2,
        count_mode="exact",
        mutation_mode="add_only",
        allowed_section_ids=["basic_consolidation"],
        target_section_ids=["basic_consolidation"],
        preserve_section_scores=True,
    )
    result = asyncio.run(execute_tool("exercise_apply_question_batch", tc, {
        "base_revision": 0,
        "additions": [
            {"section_id": "basic_consolidation", "question": _multiple_choice("MC-01")},
            {"section_id": "basic_consolidation", "question": _multiple_choice("MC-02")},
        ],
        "score_updates": [{"question_id": "Q-01", "score": 10}],
        "expected_question_type": "multiple_choice",
        "expected_type_count": 2,
        "expected_total_delta": 2,
        "allowed_section_ids": ["basic_consolidation"],
    }))
    assert result.ok, result.error
    assert builder.revision == 1
    assert builder.question_type_counts()["multiple_choice"] == 2
    assert [section["score"] for section in builder.sections] == [40, 40, 20]

    source = asyncio.run(execute_tool("exercise_get_source", tc, {}))
    assert source.output["builder_revision"] == 1
    assert source.output["question_type_counts"]["multiple_choice"] == 2
    assert {item["id"] for item in source.output["questions"]} >= {"MC-01", "MC-02"}
    stale = asyncio.run(execute_tool("exercise_apply_question_batch", tc, {
        "base_revision": 0,
        "additions": [],
        "expected_question_type": "multiple_choice",
        "expected_type_count": 2,
        "expected_total_delta": 2,
    }))
    assert not stale.ok
    assert stale.error_code == "builder_revision_conflict"
    assert builder.revision == 1


def test_atomic_question_batch_rolls_back_on_invalid_scoring(exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    before = builder.to_content()
    tc = _tool_context(builder)
    tc.runtime.baseline_content = before
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT", operation="ensure_question_type_count",
        question_type="multiple_choice", target_count=1, requested_delta=1,
        allowed_section_ids=["basic_consolidation"], target_section_ids=["basic_consolidation"],
    )
    result = asyncio.run(execute_tool("exercise_apply_question_batch", tc, {
        "base_revision": 0,
        "additions": [{"section_id": "basic_consolidation", "question": _multiple_choice("MC-BAD")}],
        "expected_question_type": "multiple_choice", "expected_type_count": 1,
        "expected_total_delta": 1,
    }))
    assert not result.ok
    assert result.output["rolled_back"] is True
    assert builder.revision == 0
    assert builder.to_content() == before


def test_atomic_question_batch_rolls_back_on_locked_section(exercise_data):
    from app.agent.registry import execute_tool

    builder = ExerciseBuilder(exercise_data)
    before = builder.to_content()
    tc = _tool_context(builder)
    tc.runtime.baseline_content = before
    tc.runtime.locks = [SimpleNamespace(json_path="$.sections[basic_consolidation].blocks")]
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT", operation="ensure_question_type_count",
        question_type="multiple_choice", target_count=1, requested_delta=1,
        allowed_section_ids=["basic_consolidation"], target_section_ids=["basic_consolidation"],
    )
    result = asyncio.run(execute_tool("exercise_apply_question_batch", tc, {
        "base_revision": 0,
        "additions": [{"section_id": "basic_consolidation", "question": _multiple_choice("MC-LOCKED")}],
        "expected_question_type": "multiple_choice", "expected_type_count": 1,
        "expected_total_delta": 1,
    }))
    assert not result.ok
    assert result.output["rolled_back"] is True
    assert builder.to_content() == before


# ---------------------------------------------------------------------------
# 意图识别
# ---------------------------------------------------------------------------


def test_intent_initial_is_generate():
    decision = asyncio.run(infer_exercise_intent(None, "initial", ""))
    assert decision.intent == "GENERATE"
    assert decision.confidence == 1.0


def test_intent_mock_fallback_keyword():
    decision = asyncio.run(infer_exercise_intent(None, "message", "把第三题的分值改为 10 分"))
    assert decision.intent == "SCORING_ADJUST"
    decision = asyncio.run(infer_exercise_intent(None, "message", "删除第一题"))
    assert decision.intent == "QUESTION_EDIT"
    assert decision.requires_confirmation is True


@pytest.mark.parametrize(
    ("current", "delta", "confirmation"),
    [(0, 5, False), (3, 2, False), (5, 0, False), (6, -1, True)],
)
def test_exact_multiple_choice_count_contract(current, delta, confirmation):
    decision = asyncio.run(infer_exercise_intent(
        None,
        "message",
        "补充一下多选题，补充到五题",
        current_type_counts={"multiple_choice": current},
    ))
    assert decision.intent == "QUESTION_EDIT"
    assert decision.operation == "ensure_question_type_count"
    assert decision.question_type == "multiple_choice"
    assert decision.target_count == 5
    assert decision.requested_delta == delta
    assert decision.mutation_mode == "add_only"
    assert decision.requires_confirmation is confirmation


def test_explicit_exact_count_reduction_is_authorized_without_confirmation():
    decision = asyncio.run(infer_exercise_intent(
        None,
        "message",
        "我要有五道多选，现在怎么有那么多道，进行缩减",
        current_type_counts={"multiple_choice": 9},
    ))
    assert decision.intent == "QUESTION_EDIT"
    assert decision.operation == "ensure_question_type_count"
    assert decision.question_type == "multiple_choice"
    assert decision.target_count == 5
    assert decision.requested_delta == -4
    assert decision.mutation_mode == "delete_excess"
    assert decision.destructive is True
    assert decision.requires_confirmation is False


def test_count_parser_prefers_requested_target_over_observed_current_count():
    decision = asyncio.run(infer_exercise_intent(
        None,
        "message",
        "现在有六道多选，但是我只要五道，请进行删减",
        current_type_counts={"multiple_choice": 6},
    ))
    assert decision.target_count == 5
    assert decision.current_count == 6
    assert decision.requested_delta == -1
    assert decision.mutation_mode == "delete_excess"
    assert decision.requires_confirmation is False


def test_explicit_delete_last_question_outranks_equal_count_no_change():
    decision = asyncio.run(infer_exercise_intent(
        None,
        "message",
        "我总共要有五道多选，去掉最后一题多选题",
        current_type_counts={"multiple_choice": 5},
    ))
    assert decision.target_count == 4
    assert decision.requested_delta == -1
    assert decision.delete_position == "last"
    assert decision.mutation_mode == "delete_excess"
    assert decision.requires_confirmation is False


def test_atomic_question_batch_can_delete_only_excess_target_type(exercise_data):
    from app.agent.registry import execute_tool

    source = _thirty_thirty_five_thirty_five_with_three_multi(exercise_data)
    builder = ExerciseBuilder(source)
    tc = _tool_context(builder)
    tc.runtime.baseline_content = builder.to_content()
    tc.runtime.intent_plan = ExerciseIntentDecision(
        intent="QUESTION_EDIT",
        operation="ensure_question_type_count",
        question_type="multiple_choice",
        target_count=1,
        current_count=3,
        requested_delta=-2,
        count_mode="exact",
        mutation_mode="delete_excess",
        allowed_section_ids=["understanding_application"],
        target_section_ids=["understanding_application"],
        preserve_section_scores=True,
    )
    result = asyncio.run(execute_tool("exercise_apply_question_batch", tc, {
        "base_revision": 0,
        "removals": ["MC-02", "MC-03"],
        "score_updates": [{"question_id": "MC-01", "score": 15}],
        "expected_question_type": "multiple_choice",
        "expected_type_count": 1,
        "expected_total_delta": -2,
        "allowed_section_ids": ["understanding_application"],
    }))
    assert result.ok, result.error
    assert set(result.output["removed_question_ids"]) == {"MC-02", "MC-03"}
    assert result.output["actual_delta"] == -2
    assert builder.question_type_counts()["multiple_choice"] == 1
    assert [item["score"] for item in builder.sections] == [30, 35, 35]


def test_intent_chain_for_generate():
    chain = agent_chain_for_intent("GENERATE", "initial")
    assert chain == [
        "context_researcher", "exercise_architect", "question_designer",
        "visual_specifier", "exercise_qa", "finalizer",
    ]


class _ScriptedIntentProvider:
    def __init__(self, decision: ExerciseIntentDecision):
        self._decision = decision
        self.calls = 0

    async def structured(self, system, prompt, schema):
        self.calls += 1
        if schema is ExerciseIntentDecision:
            return self._decision
        raise TypeError(f"未预期的 schema：{schema}")


def test_intent_llm_path_uses_provider():
    decision = ExerciseIntentDecision(
        intent="QUESTION_EDIT", confidence=0.9,
        target_question_ids=["Q-01"], summary="修改题目",
    )
    provider = _ScriptedIntentProvider(decision)
    result = asyncio.run(infer_exercise_intent(provider, "message", "改一下 Q-01"))
    assert result.intent == "QUESTION_EDIT"
    assert result.target_question_ids == ["Q-01"]
    assert provider.calls == 1


def test_intent_llm_filters_hallucinated_target_ids():
    """回归：LLM 把"第六题"编造成 q6（真实 ID 是 ex_06）时，
    意图识别应过滤掉不在 available_question_ids 中的 ID。"""
    def _decision():
        return ExerciseIntentDecision(
            intent="QUESTION_EDIT", confidence=0.9,
            target_question_ids=["q6", "ex_06"], summary="润色第六题",
        )

    provider = _ScriptedIntentProvider(_decision())
    result = asyncio.run(infer_exercise_intent(
        provider, "message", "润色第六题的格式",
        available_question_ids=["ex_01", "ex_02", "ex_06"],
    ))
    assert result.target_question_ids == ["ex_06"]
    # available 为 None 时不过滤（保持兼容）
    provider2 = _ScriptedIntentProvider(_decision())
    result2 = asyncio.run(infer_exercise_intent(provider2, "message", "润色第六题的格式"))
    assert result2.target_question_ids == ["q6", "ex_06"]


# ---------------------------------------------------------------------------
# Runtime 全链路（Mock）
# ---------------------------------------------------------------------------


class _FakeArtifacts:
    """模拟 PipelineArtifactManager 的最小实现（latest/create 内存版）。"""

    def __init__(self):
        self.store: dict[str, dict] = {}

    async def create(self, artifact_type, name, data, **kwargs):
        payload = {
            "id": f"a-{artifact_type}", "artifact_type": artifact_type, "name": name,
            "version": 1, "status": "validated", "data": data, "file_path": "",
            "producer_agent": kwargs.get("producer_agent", ""), "producer_tool": "",
            "created_by_step_index": kwargs.get("step_index", 0),
            "dependencies": [], "created_at": "", "updated_at": "",
        }
        self.store[artifact_type] = payload
        return payload

    async def latest(self, artifact_type, name="default"):
        return self.store.get(artifact_type)


def _make_runtime(provider=None, *, trigger="initial", instruction="", mode=None):
    bp_content = dict(BP)
    context = ContextState(
        blueprint=bp_content, profile=None, knowledge={},
        user_instruction=instruction, locks=[],
    )
    runtime = ExerciseAgentRuntime(
        course=None, task=None,
        blueprint=SimpleNamespace(content_json=bp_content),
        generation_run=None, pipeline_run=None, profile=None,
        provider=provider, config=None, knowledge_context={},
        source_versions={}, locks=[], source_artifact=None,
        user_message=None, trigger_type=trigger,
        context=context, artifacts=_FakeArtifacts(), emitter=None,
        request_metadata={"mode": mode},
    )
    return runtime


def test_runtime_initial_mock_publishes_valid_exercise():
    from app.providers.llm.mock import MockProvider

    runtime = _make_runtime(MockProvider(), trigger="initial")
    asyncio.run(runtime.run())
    assert runtime.result_status == "applied"
    assert runtime.changed is True
    content = runtime.draft_content
    assert content["schema_version"] == "2.0"
    assert [s["score"] for s in content["sections"]] == [40, 40, 20]
    assert content["paper_settings"]["total_score"] == 100
    # 发布门禁通过 → review_summary 终态回填
    assert content["review_summary"]["rules_status"] == "passed"
    assert content["review_summary"]["text_review_status"] == "passed"
    assert not blocking_issues(exercise_validate_rules(CourseBlueprintSchema.model_validate(BP), content))


def test_runtime_message_mock_no_change_for_qa_only():
    from app.providers.llm.mock import MockProvider

    runtime = _make_runtime(MockProvider(), trigger="message", instruction="检查一下质量")
    asyncio.run(runtime.run())
    assert runtime.result_status == "no_change"
    assert runtime.changed is False


class _CountEditProvider:
    def __init__(self, tool_input: dict):
        self.tool_input = tool_input
        self.agent_round = 0
        self.calls = 0

    async def structured(self, system, prompt, schema):
        self.calls += 1
        if schema is ExerciseIntentDecision:
            # Deliberately wrong LLM routing: deterministic normalization must win.
            return ExerciseIntentDecision(intent="STRUCTURE_EDIT", structural=True, confidence=0.95)
        raise TypeError(f"unexpected schema {schema}")

    async def stream_decision(self, system, prompt, schema):
        from app.agent.agents.exercise.qa import LlmExerciseQaResult

        self.calls += 1
        if schema is AgentDecision:
            if self.agent_round == 0:
                decision = AgentDecision(tool_calls=[ToolCall(
                    tool_name="exercise_apply_question_batch", input=self.tool_input,
                )])
            else:
                decision = AgentDecision(completed=True, output={}, summary="批量修改完成")
            self.agent_round += 1
        elif schema is LlmExerciseQaResult:
            decision = LlmExerciseQaResult(issues=[], summary="新增题目通过 scoped QA")
        else:
            raise TypeError(f"unexpected stream schema {schema}")
        yield "decision_ready", decision


def test_runtime_exact_count_edit_is_bounded_and_preserves_30_35_35(exercise_data):
    source_content = _thirty_thirty_five_thirty_five_with_three_multi(exercise_data)
    q3 = source_content["sections"][1]["blocks"][0]["sub_questions"][0]
    q4 = source_content["sections"][1]["blocks"][0]["sub_questions"][1]
    provider = _CountEditProvider({
        "base_revision": 0,
        "additions": [
            {"section_id": "understanding_application", "question": _multiple_choice("MC-04")},
            {"section_id": "understanding_application", "question": _multiple_choice("MC-05")},
        ],
        "score_updates": [
            {"question_id": q3["id"], "score": 5, "scoring_points": [{**q3["scoring_points"][0], "points": 5}]},
            {"question_id": q4["id"], "score": 5, "scoring_points": [{**q4["scoring_points"][0], "points": 5}]},
        ],
        "expected_question_type": "multiple_choice",
        "expected_type_count": 5,
        "expected_total_delta": 2,
        "allowed_section_ids": ["understanding_application"],
    })
    runtime = _make_runtime(
        provider, trigger="message", instruction="补充一下多选题，补充到五题",
    )
    runtime.source_artifact = SimpleNamespace(
        content_json=source_content, version=7, content_markdown="",
    )
    runtime.context.source_artifact = runtime.source_artifact
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.after_type_counts["multiple_choice"] == 5
    assert runtime.requested_delta == 2
    assert runtime.actual_delta == 2
    assert [item["score"] for item in runtime.draft_content["sections"]] == [30, 35, 35]
    assert runtime.builder.find_question("Q-01")[0]["question_type"] == "single_choice"
    assert runtime.builder.find_question("Q-02")[0]["question_type"] == "fill_blank"


def test_runtime_explicit_count_reduction_finishes_without_confirmation(exercise_data):
    source_content = _thirty_thirty_five_thirty_five_with_three_multi(exercise_data)
    provider = _CountEditProvider({
        "base_revision": 0,
        "removals": ["MC-02", "MC-03"],
        "score_updates": [{"question_id": "MC-01", "score": 15}],
        "expected_question_type": "multiple_choice",
        "expected_type_count": 1,
        "expected_total_delta": -2,
        "allowed_section_ids": ["understanding_application"],
    })
    runtime = _make_runtime(
        provider,
        trigger="message",
        instruction="我要有一道多选，现在怎么有那么多道，进行缩减",
    )
    runtime.source_artifact = SimpleNamespace(
        content_json=source_content, version=8, content_markdown="",
    )
    runtime.context.source_artifact = runtime.source_artifact
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.confirmation_request is None
    assert runtime.after_type_counts["multiple_choice"] == 1
    assert runtime.requested_delta == -2
    assert runtime.actual_delta == -2
    assert [item["score"] for item in runtime.draft_content["sections"]] == [30, 35, 35]


def test_runtime_explicit_delete_last_multiple_choice_is_not_short_circuited(exercise_data):
    source_content = _thirty_thirty_five_thirty_five_with_three_multi(exercise_data)
    provider = _CountEditProvider({})
    runtime = _make_runtime(
        provider,
        trigger="message",
        instruction="我总共要有三道多选，去掉最后一题多选题",
    )
    runtime.source_artifact = SimpleNamespace(
        content_json=source_content, version=9, content_markdown="",
    )
    runtime.context.source_artifact = runtime.source_artifact
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.intent_plan.delete_question_ids == ["MC-03"]
    assert runtime.builder.find_question("MC-03")[0] is None
    assert runtime.after_type_counts["multiple_choice"] == 2
    assert runtime.actual_delta == -1
    assert [item["score"] for item in runtime.draft_content["sections"]] == [30, 35, 35]
    assert provider.calls <= 4
    assert sum(item["decision_rounds"] for item in runtime.agent_stats.values()) <= 6
    assert sum(item["tool_calls"] for item in runtime.agent_stats.values()) == 1


def test_runtime_exact_count_already_satisfied_is_no_change(exercise_data):
    from app.providers.llm.mock import MockProvider

    source_content = _thirty_thirty_five_thirty_five_with_three_multi(exercise_data)
    group = source_content["sections"][1]["blocks"][0]
    _set_score(group["sub_questions"][0], 5)
    _set_score(group["sub_questions"][1], 5)
    group["sub_questions"].extend([_multiple_choice("MC-04"), _multiple_choice("MC-05")])
    source_content = ExerciseContent.model_validate(source_content).model_dump()
    runtime = _make_runtime(
        MockProvider(), trigger="message", instruction="补充一下多选题，补充到五题",
    )
    runtime.source_artifact = SimpleNamespace(content_json=source_content, version=8, content_markdown="")
    runtime.context.source_artifact = runtime.source_artifact
    asyncio.run(runtime.run())
    assert runtime.result_status == "no_change"
    assert runtime.after_type_counts["multiple_choice"] == 5
    assert runtime.requested_delta == 0
    assert not runtime.agent_stats


def test_normal_message_does_not_emit_auto_repair_started(exercise_data):
    from app.services.exercise_pipeline_service import _run_pipeline_message

    events: list[str] = []

    class Emitter:
        async def agent_status_delta(self, *args, **kwargs):
            events.append("agent_status_delta")

        async def revision_started(self, *args, **kwargs):
            events.append("revision_started")

        async def emit_domain(self, event_type, **kwargs):
            events.append(event_type)

        async def agent_message_append(self, *args, **kwargs):
            events.append("agent_message_append")

    class Runtime:
        emitter = Emitter()
        selected_section_ids = []
        result_status = "applied"
        active_intent = "QUESTION_EDIT"
        affected_section_ids = []
        draft_content = exercise_data
        dialogue_summary = ""
        current_agent_key = ""
        checkpoint_start = 0

        async def run(self):
            return None

        def pause_requested(self):
            return False

    source = SimpleNamespace(version=1, content_json=exercise_data)
    message = SimpleNamespace(content="润色一道题", metadata_json={})
    asyncio.run(_run_pipeline_message(Runtime(), source, message))
    assert "revision_started" not in events
    assert "repair.started" not in events
    assert "artifact.revision.preparing" in events


# ---------------------------------------------------------------------------
# 知识上下文摘要
# ---------------------------------------------------------------------------


def test_llm_summarize_mock_falls_back_to_bounded():
    from app.services.project_knowledge_service import _llm_summarize_sibling
    from app.providers.llm.mock import MockProvider

    content = {"sections": [{"id": "basic_consolidation", "title": "基础巩固", "score": 40}]}
    summary = asyncio.run(_llm_summarize_sibling(MockProvider(), "exercise", content, 5000))
    assert "semantic_summary" not in summary
    assert summary.get("sections")


class _ScriptedSummaryProvider:
    def __init__(self, summary):
        self._summary = summary
        self.calls = 0

    async def structured(self, system, prompt, schema):
        self.calls += 1
        return self._summary


def test_llm_summarize_uses_provider_and_marks_semantic():
    from app.services.project_knowledge_service import _llm_summarize_sibling

    class Summary:
        summary = "三区练习，总分 100，覆盖 OBJ-01/OBJ-02。"
        key_points = ["基础巩固 40 分"]
        alignment_notes = ["每个目标至少一道计分题"]
        must_keep_refs = ["OBJ-01", "OBJ-02", "KP-01"]

    provider = _ScriptedSummaryProvider(Summary())
    content = {"sections": [{"id": "basic_consolidation", "title": "基础巩固", "score": 40}]}
    summary = asyncio.run(_llm_summarize_sibling(provider, "exercise", content, 5000))
    assert summary["semantic_summary"] is True
    assert "OBJ-01" in summary["must_keep_refs"]
    assert provider.calls == 1


def test_summary_cache_key_stable():
    from app.services.project_knowledge_service import _summary_cache_key

    assert _summary_cache_key("exercise", 3, 2) == "exercise:v3:bp2"
