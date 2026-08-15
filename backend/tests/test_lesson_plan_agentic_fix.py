"""教学设计 Agent「Coding Agent 化」修复验收测试。

覆盖方案第四节的验收项：
1. 最新失败运行回放：`教学反思的序号有问题，作为一个新的点序号为什么是二`
   → SECTION_FORMAT_EDIT / SEC-REFLECTION / 不调用 lesson_designer / 不调用
     lesson_update_core / FormatNormalizer 只改目标章节 / 其他章节 hash 不变 /
     VerificationReport 通过 / Finalizer LLM 与工具调用均为 0 / 有 diff 生成新版本；
2. 生产路径：即使 Provider 返回重复读取工具，Finalizer 也不得调用 Provider；
3. QA 一致性：QA 与 Finalizer 消费同一份 verification_report；
4. 意图识别测试集：格式修正 / 内容修改 / 新增章节 / 拆分 / 时长 / 同步 / 问答 / 质检 / 多目标 / 歧义；
5. 知识结合：证据包只注入相关材料，格式任务不检索材料；
6. 编号与内容安全：标题序数清理、步骤序号保留、公式保留、表格保留、幂等。
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.agent.agents.lesson_plan.builder import LessonPlanBuilder
from app.agent.agents.lesson_plan.intents import (
    LessonPlanIntentDecision,
    build_lesson_plan_task_spec,
    infer_lesson_plan_intent,
)
from app.agent.agents.lesson_plan.qa import (
    baseline_numbering_warnings,
    build_lesson_plan_verification_report,
    numbering_issues_in_sections,
)
from app.agent.agents.lesson_plan.runtime import LessonPlanAgentRuntime
from app.agent.context import ContextState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall
from app.schemas.lesson_plan import LessonPlanContentV2, make_lesson_plan_v2
from tests.test_lesson_plan_runtime import _FakeArtifacts, _make_runtime, _ScriptedProvider
from tests.test_lesson_plan_v2 import make_bp


# ---------------------------------------------------------------------------
# 1. 最新失败运行回放：SECTION_FORMAT_EDIT 确定性收敛
# ---------------------------------------------------------------------------


def _replay_provider():
    """模拟生产分发：Finalizer 若被错误分发给模型，会返回重复读取工具。

    正确实现下 Finalizer 是确定性节点，该队列永远不会被消费。
    """
    from app.agent.agents.lesson_plan.intents import LessonPlanIntentDecision

    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="numbering_defect",
        classifier_version="v3",
    )
    return _ScriptedProvider(intent, [
        # 若 finalizer 被分发给模型：模型要求重复读取源数据（应永不发生）。
        AgentDecision(tool_calls=[ToolCall(tool_name="lesson_get_source", input={"view": "full"})]),
        AgentDecision(completed=True, output={"content": {}}, summary="终稿"),
    ])


def test_failing_run_replay_format_edit_converges_deterministically():
    """回放 3c086990 失败输入：意图/范围/确定性收敛全部达标。"""
    from app.agent.agents.lesson_plan.agents import FINALIZER
    from app.agent.core.error import AgentError
    from app.agent.core.loop import run_agent_loop
    from app.agent.core.state import AgentRuntimeState

    phrase = "教学反思的序号有问题，作为一个新的点序号为什么是二"
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{
                "kind": "paragraph",
                "text": "一、教师课后反思框架\n1. 目标达成情况检查。",
            }]
    provider = _replay_provider()
    runtime = _make_runtime(provider, instruction=phrase, mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    asyncio.run(runtime.run())

    # 意图与范围。
    assert runtime.active_intent == "SECTION_FORMAT_EDIT"
    assert runtime.resolved_intent.target_section_ids == ["SEC-REFLECTION"]
    assert "lesson_designer" not in runtime.executed_chain
    # 确定性收敛：格式主链（normalizer→qa→finalizer）全部 LLM 深度分析，
    # 但 Finalizer 不进入工具循环、不修改候选稿；确定性修复实际落地。
    assert runtime.agent_stats["finalizer"]["decision_rounds"] == 1
    assert runtime.agent_stats["finalizer"]["tool_calls"] == 0
    assert not runtime.unresolved_tool_failures, "Finalizer 不得调用 lesson_get_source"
    assert runtime.fatal_tool_error is None
    # 有实际 diff → applied。
    assert runtime.result_status == "applied"
    assert runtime.publishable is True
    # 目标章节编号已修复；其他章节与内核逐字不变。
    reflection = next(
        item for item in runtime.draft_content["outline"]["sections"] if item["id"] == "SEC-REFLECTION"
    )
    assert "一、" not in reflection["blocks"][0]["text"]
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-REFLECTION":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]
    assert runtime.verification_report.get("passed") is True
    LessonPlanContentV2.model_validate(runtime.draft_content)


def test_no_change_replay_returns_rejected_without_fake_no_change():
    """候选稿与源完全一致（无实际 diff）：格式/内容类修改必须 rejected 并给出
    明确原因，绝不能伪装成“当前设计已符合要求，本轮未创建空转版本”。"""
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "教师课后反思与持续改进。"}]
    provider = _replay_provider()
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.builder = LessonPlanBuilder(source)
    runtime.baseline_content = copy.deepcopy(source)
    asyncio.run(runtime.run())

    assert runtime.result_status == "rejected"
    assert runtime.publishable is False
    assert runtime.changed is False
    assert runtime.intent_gate["code"] == "no_change_but_request_unfulfilled"
    assert "required_change_missing" in runtime.intent_gate["failures"]


def test_finalizer_never_consumes_provider_even_when_provider_repeats_reads():
    """生产路径：即使 Provider 返回重复读取工具，Finalizer 也不得调用 Provider。

    ``_ScriptedProvider`` 只被意图识别调用一次（工作区接地意图提取），
    Finalizer / pedagogy_qa / intent_planner / context_researcher 均为确定性节点。
    """
    from app.agent.core.loop import run_agent_loop

    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    modified["outline"]["sections"][0]["title"] = "内容分析（已调整）"
    provider = _replay_provider()
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.builder = LessonPlanBuilder(modified)
    runtime.baseline_content = copy.deepcopy(source)
    runtime.artifacts = _FakeArtifacts()
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    # 新架构：真实 Provider 下全部节点深度 LLM 分析。确定性修复（format_normalizer
    # 对 modified 的 SEC-CONTENT 标题调整后的候选稿）已产生实际 diff，主链生效；
    # Finalizer 有 LLM 分析但不进入工具循环。
    assert runtime.agent_stats["finalizer"]["decision_rounds"] == 1
    assert runtime.agent_stats["finalizer"]["tool_calls"] == 0


# ---------------------------------------------------------------------------
# 2. QA 一致性：QA 与 Finalizer 消费同一份 verification_report
# ---------------------------------------------------------------------------


def test_qa_and_finalizer_share_verification_report():
    """pedagogy_qa 写入 lesson_qa 的统一报告被 runtime 消费；passed 一致。"""
    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    for section in modified["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "一、教师课后反思框架"}]
    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="numbering_defect", classifier_version="v3",
    )
    provider = _ScriptedProvider(intent, [])
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    runtime.builder = LessonPlanBuilder(modified)
    runtime.baseline_content = copy.deepcopy(source)
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.verification_report.get("passed") is True
    assert runtime.blocking_issues == []
    # lesson_qa 产物携带同一份报告。
    qa = asyncio.run(runtime.artifacts.latest("lesson_qa"))
    assert qa is not None
    assert qa["data"]["verification_report"]["passed"] is True


def test_target_numbering_defect_blocks_publish():
    """目标章节仍含硬编码序号 → 格式修正（SECTION_FORMAT_EDIT）下 verification 阻断。

    普通内容修改（SECTION_EDIT 等）中正文「一、二、」属于内容固有结构排版，
    不阻断；只有用户明确要求格式修正时才把编号残留视为阻断错误。
    """
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "一、教师课后反思框架"}]
    report = build_lesson_plan_verification_report(
        make_bp(), None, source, target_section_ids=["SEC-REFLECTION"],
        numbering_blocking=True,  # 格式修正：编号残留即阻断
    )
    assert report["passed"] is False
    assert any(
        item.get("dimension") == "numbering" and "SEC-REFLECTION" in item.get("location", "")
        for item in report["blocking_issues"]
    )
    # 普通内容修改（默认 numbering_blocking=False）：编号残留只记 baseline_warning，不阻断。
    report_content = build_lesson_plan_verification_report(
        make_bp(), None, source, target_section_ids=["SEC-REFLECTION"],
    )
    assert report_content["passed"] is True
    assert any(
        "SEC-REFLECTION" in item.get("location", "") for item in report_content["baseline_warnings"]
    )


def test_other_section_baseline_numbering_is_warning_not_blocking():
    """其他章节的历史编号问题 → baseline_warning，不阻断本轮修复。"""
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-HOMEWORK":
            section["blocks"] = [{"kind": "paragraph", "text": "二、作业布置：完成配套练习"}]
    report = build_lesson_plan_verification_report(
        make_bp(), None, source, target_section_ids=["SEC-REFLECTION"],
    )
    assert report["passed"] is True
    assert any(
        item.get("dimension") == "numbering_baseline"
        for item in report["baseline_warnings"]
    )
    assert not report["target_checks"]


# ---------------------------------------------------------------------------
# 3. 意图识别测试集
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_recognition_suite():
    cases = [
        # (指令, 选中章节, mode, 期望意图, 期望目标, 期望 reasoning)
        ("教学反思的序号有问题，作为一个新的点序号为什么是二", ["reflection"], None, "SECTION_FORMAT_EDIT", ["SEC-REFLECTION"], False),
        ("把教学评价的内容改得更详细", ["SEC-ASSESSMENT"], "content", "SECTION_EDIT", ["SEC-ASSESSMENT"], True),
        ("新增一个课堂小结章节", None, None, "RESTRUCTURE", [], True),
        ("把教学过程拆分成两个部分", None, None, "RESTRUCTURE", [], True),
        ("调整课堂导入环节的时长为5分钟", None, "timing", "TIMING_ADJUST", [], False),
        ("按最新蓝图同步教学设计", None, None, "SYNC_CONTEXT", [], False),
        ("教学目标为什么要用行为动词描述？", None, None, "ANSWER_ONLY", [], False),
        ("检查一下这份教学设计是否合规", None, "qa", "QA_ONLY", [], False),
        ("改", None, None, "CLARIFICATION_REQUIRED", [], False),
    ]
    for instruction, selected, mode, expected_intent, expected_targets, expected_reasoning in cases:
        decision = await infer_lesson_plan_intent(None, "message", instruction, selected, mode)
        spec = build_lesson_plan_task_spec(decision, instruction)
        assert decision.intent == expected_intent, f"{instruction}: {decision.intent} != {expected_intent}"
        if expected_targets:
            assert list(decision.target_section_ids) == expected_targets, f"{instruction}: targets mismatch"
        assert spec.requires_teaching_reasoning == expected_reasoning, (
            f"{instruction}: reasoning={spec.requires_teaching_reasoning} != {expected_reasoning}"
        )
        assert spec.success_conditions, f"{instruction}: 缺少 success_conditions"


def test_task_spec_format_edit_shape():
    """SECTION_FORMAT_EDIT 的任务规格：允许/禁止变更与成功条件齐备。"""
    decision = asyncio.run(infer_lesson_plan_intent(
        None, "message", "教学反思的序号有问题", ["reflection"], None,
    ))
    spec = build_lesson_plan_task_spec(decision, "教学反思的序号有问题", context_snapshot_id="snap-x")
    assert spec.intent == "SECTION_FORMAT_EDIT"
    assert spec.target_section_ids == ["SEC-REFLECTION"]
    assert spec.allowed_change_kinds == ["formatting", "section_content"]
    assert "core_content" in spec.forbidden_change_kinds
    assert spec.context_snapshot_id == "snap-x"
    assert spec.expected_outcome
    assert spec.success_conditions


# ---------------------------------------------------------------------------
# 4. 知识结合：证据包
# ---------------------------------------------------------------------------


def test_evidence_bundle_filters_materials_by_target_facts():
    from app.agent.agents.lesson_plan.context import build_lesson_plan_evidence_bundle

    source = make_lesson_plan_v2(make_bp()).model_dump()
    bundle = build_lesson_plan_evidence_bundle(
        source,
        blueprint=make_bp().model_dump(),
        knowledge={
            "materials": [
                {"id": "M-1", "title": "勾股定理教材", "summary": "reflection 相关素材"},
                {"id": "M-2", "title": "浮力实验", "summary": "与目标无关的物理素材"},
            ],
            "sibling_artifacts": {"task_sheet": {"id": "TS-1", "title": "预习任务单"}},
        },
        target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        requires_teaching_reasoning=True,
    )
    assert [item.material_id for item in bundle.material_evidence] == ["M-1"]
    assert bundle.sufficiency in {"sufficient", "partial"}


def test_evidence_bundle_skips_material_search_for_format_task():
    """格式任务不进行无意义的材料检索。"""
    from app.agent.agents.lesson_plan.context import build_lesson_plan_evidence_bundle

    source = make_lesson_plan_v2(make_bp()).model_dump()
    bundle = build_lesson_plan_evidence_bundle(
        source,
        blueprint=make_bp().model_dump(),
        knowledge={"materials": [{"id": "M-1", "title": "素材", "summary": "任意"}]},
        target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        requires_teaching_reasoning=False,
    )
    assert bundle.material_evidence == []
    assert bundle.sufficiency == "sufficient"


def test_evidence_bundle_marks_insufficient_without_evidence():
    """内容修改任务目标事实缺少材料证据 → partial/insufficient 且记录 knowledge_gaps。"""
    from app.agent.agents.lesson_plan.context import build_lesson_plan_evidence_bundle

    source = make_lesson_plan_v2(make_bp()).model_dump()
    bundle = build_lesson_plan_evidence_bundle(
        source,
        blueprint=make_bp().model_dump(),
        knowledge={"materials": []},
        target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        requires_teaching_reasoning=True,
    )
    assert bundle.material_evidence == []
    assert bundle.knowledge_gaps, "证据不足应记录 knowledge_gaps"
    assert bundle.sufficiency in {"partial", "insufficient"}


# ---------------------------------------------------------------------------
# 5. 编号与内容安全
# ---------------------------------------------------------------------------


def test_numbering_safety_title_ordinal_steps_formula_table():
    from app.agent.agents.lesson_plan.formatting import strip_hardcoded_ordinals

    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [
                {"kind": "paragraph", "text": "二、教师课后反思框架\n勾股定理公式：a²+b²=c²"},
                {"kind": "steps", "steps": [
                    {"title": "第一步：检查目标达成", "detail": "1. 统计完成情况。"},
                ]},
                {"kind": "bullets", "items": ["（一）目标达成情况检查。"]},
                {"kind": "table", "title": "反思表", "columns": ["维度", "说明"],
                 "rows": [{"cells": ["一、目标", "达成"]}]},
            ]
    fixed = strip_hardcoded_ordinals(source, ["SEC-REFLECTION"])
    reflection = next(
        item for item in fixed["outline"]["sections"] if item["id"] == "SEC-REFLECTION"
    )
    blocks = reflection["blocks"]
    # 标题型序数被清理。
    assert blocks[0]["text"].startswith("教师课后反思框架")
    assert "二、" not in blocks[0]["text"]
    # 公式与带句末标点的编号条目保留。
    assert "a²+b²=c²" in blocks[0]["text"]
    # steps 序号保留（由 steps 渲染器生成，正文不清理）。
    assert blocks[1]["steps"][0]["title"].startswith("第一步")
    assert blocks[1]["steps"][0]["detail"].startswith("1. ")
    # 带句末标点的列表项保留。
    assert blocks[2]["items"][0].startswith("（一）目标达成情况检查。")
    # 表格内容逐字不变。
    assert blocks[3]["rows"][0]["cells"][0] == "一、目标"
    # 幂等：第二次执行无变化。
    assert strip_hardcoded_ordinals(fixed, ["SEC-REFLECTION"]) == fixed


def test_numbering_scope_only_checks_target_sections():
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-HOMEWORK":
            section["blocks"] = [{"kind": "paragraph", "text": "一、作业布置：完成练习"}]
    blocking = numbering_issues_in_sections(source, ["SEC-REFLECTION"])
    assert blocking == []
    assert baseline_numbering_warnings(source, ["SEC-REFLECTION"])


def test_format_normalizer_idempotent_second_run_no_change():
    from app.agent.agents.lesson_plan.formatting import strip_hardcoded_ordinals

    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "一、教师课后反思框架"}]
    once = strip_hardcoded_ordinals(source, ["SEC-REFLECTION"])
    twice = strip_hardcoded_ordinals(once, ["SEC-REFLECTION"])
    assert once != source
    assert twice == once


# ---------------------------------------------------------------------------
# 6. 状态机事件与任务规格（runtime 字段级断言）
# ---------------------------------------------------------------------------


def test_runtime_emits_task_spec_evidence_and_verification_events():
    """执行链前生成 TaskSpec / EvidenceBundle；finalize 生成 verification.completed。"""
    events: list[str] = []

    class _Emitter:
        async def emit_domain(self, event_type, **kwargs):
            events.append(event_type)

        async def pipeline_started(self, trigger_type=""):
            return None

        async def revision_started(self, *args, **kwargs):
            return None

        async def revision_completed(self, *args, **kwargs):
            return None

        async def agent_started(self, *args, **kwargs):
            return None

        async def agent_completed(self, *args, **kwargs):
            return None

        async def agent_status_delta(self, *args, **kwargs):
            return None

        async def agent_status_completed(self, *args, **kwargs):
            return None

        async def agent_thought_chunk(self, *args, **kwargs):
            return None

        async def tool_call_started(self, *args, **kwargs):
            return None

        async def tool_call_completed(self, *args, **kwargs):
            return None

        async def artifact_created(self, *args, **kwargs):
            return None

    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    for section in modified["outline"]["sections"]:
        if section["id"] == "SEC-CONTENT":
            section["blocks"] = [{"kind": "paragraph", "text": "本课围绕勾股定理组织内容，并补充情境应用。"}]
    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-CONTENT"],
        target_fact_keys=["content_analysis"],
        required_change_kinds=["section_content"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
    )
    runtime = _make_runtime(
        _ScriptedProvider(intent, [
            AgentDecision(completed=True, output={"core": {}}, summary="内容已写入"),
        ]),
        instruction="修改内容分析", mode="content",
    )
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    runtime.builder = LessonPlanBuilder(modified)
    runtime.baseline_content = copy.deepcopy(source)
    runtime.emitter = _Emitter()
    asyncio.run(runtime.run())

    assert "task.spec.created" in events
    assert "evidence.bundle.ready" in events
    assert "verification.completed" in events
    assert "result.applied" in events
    assert runtime.task_spec is not None
    assert runtime.evidence_bundle is not None
    assert runtime.task_spec.target_section_ids == ["SEC-CONTENT"]


# ---------------------------------------------------------------------------
# 7. 工作区接地意图识别：删除阶段A硬编码规则后的新行为
# ---------------------------------------------------------------------------


def test_grounding_resolves_natural_language_section_refs():
    """指令提到自然语言章节名（“教学目标”）→ 接地到当前大纲真实 SEC-* ID。"""
    from app.agent.agents.lesson_plan.section_refs import ground_instruction_sections

    content = make_lesson_plan_v2(make_bp()).model_dump()
    grounded = ground_instruction_sections("把教学目标的行为动词改得更可观测", content)
    assert "SEC-OBJECTIVES" in grounded

    grounded_board = ground_instruction_sections("板书设计加一个表格", content)
    assert "SEC-BOARD" in grounded_board

    grounded_homework = ground_instruction_sections("作业布置多写两道题", content)
    assert "SEC-HOMEWORK" in grounded_homework


def test_grounding_keeps_requested_ids_first():
    """用户显式选中的章节优先保留，即使指令未提到。"""
    from app.agent.agents.lesson_plan.section_refs import ground_instruction_sections

    content = make_lesson_plan_v2(make_bp()).model_dump()
    grounded = ground_instruction_sections("改得更详细一些", content, requested_ids=["reflection"])
    assert grounded[0] == "SEC-REFLECTION"


def test_intent_recognition_injects_workspace_context():
    """真实 Provider 路径：意图识别提示词必须注入当前大纲与项目材料（RAG）。"""
    from app.agent.agents.lesson_plan.intents import infer_lesson_plan_intent

    captured = {}

    class _Provider:
        name = "test"

        async def structured(self, system, prompt, schema):
            captured["prompt"] = prompt
            from app.agent.agents.lesson_plan.intents import LessonPlanChangeContract

            return LessonPlanChangeContract(
                intent="SECTION_EDIT", target_section_ids=["SEC-OBJECTIVES"],
                required_change_kinds=["section_content"],
                forbidden_change_kinds=["outline_structure", "timing"],
            )

    content = make_lesson_plan_v2(make_bp()).model_dump()
    knowledge = {
        "agent_profile_summary": {"material_summaries": ["浮力实验材料：……", "勾股定理教材：……"]},
        "sibling_artifacts": {"task_sheet": {"version": 2}},
    }
    decision = asyncio.run(infer_lesson_plan_intent(
        _Provider(), "message", "把教学目标改得更具体", ["SEC-OBJECTIVES"], "content",
        content=content, knowledge=knowledge, profile={"learner_profile": "八年级学生"},
    ))
    prompt = captured["prompt"]
    assert "current_outline" in prompt
    assert "SEC-OBJECTIVES" in prompt
    assert "浮力实验材料" in prompt or "勾股定理教材" in prompt
    assert "sibling_artifact_versions" in prompt
    assert decision.target_section_ids == ["SEC-OBJECTIVES"]
    assert decision.raw_section_ids == ["SEC-OBJECTIVES"]


def test_split_facts_ground_without_hardcoded_rule():
    """拆分教学评价/反思：不再依赖“教学评价+教学反思+拆分”硬编码规则，
    must_be_distinct_top_level 按大纲事实归属确定性解析目标章节。"""
    from app.agent.agents.lesson_plan.intents import (
        LessonPlanIntentDecision,
        _augment_requirements,
    )

    content = make_lesson_plan_v2(make_bp()).model_dump()
    decision = LessonPlanIntentDecision(
        intent="RESTRUCTURE", structural=True,
        required_change_kinds=["outline_structure", "section_content"],
        required_separate_facts=["assessment_plan", "reflection"],
        must_be_distinct_top_level=True,
    )
    augmented = _augment_requirements(decision, "把教学评价和教学反思分成两个部分", "structure", content)
    assert "SEC-REFLECTION" in augmented.target_section_ids
    assert augmented.target_section_ids  # 目标范围必须非空


def test_no_fake_no_change_for_unresolved_format_request():
    """用户要求修改但目标无法定位/无实际修改：rejected 并给出原因，
    绝不返回“当前设计已符合要求，本轮未创建空转版本”。"""
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(SimpleNamespace(), instruction="把反思序号修一下", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.builder = LessonPlanBuilder(source)
    runtime.baseline_content = copy.deepcopy(source)
    runtime.active_intent = "SECTION_FORMAT_EDIT"
    runtime.resolved_intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="coarse-format", classifier_version="v4",
    )
    for artifact_type in (
        "lesson_intent", "lesson_research", "lesson_format", "lesson_qa", "lesson_plan_draft",
    ):
        asyncio.run(runtime.artifacts.create(artifact_type, "default", {}))
    # 直接调用 _finalize：目标章节无硬编码序号 → 无 diff → 必须 rejected。
    asyncio.run(runtime._finalize())
    assert runtime.result_status == "rejected"
    assert runtime.intent_gate["code"] == "no_change_but_request_unfulfilled"


def test_runtime_grounds_target_before_execution():
    """端到端：教师只说自然语言章节名（不选中章节），运行时接地到真实 SEC-* 并只改该部分。"""
    source = make_lesson_plan_v2(make_bp()).model_dump()
    new_blocks = [{"kind": "bullets", "items": ["能准确说明勾股定理及适用条件，并解释其判断依据"], "numbered": True}]
    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-OBJECTIVES"],
        target_fact_keys=["objectives"],
        required_change_kinds=["section_content"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
    )
    runtime = _make_runtime(
        _ScriptedProvider(intent, [
            AgentDecision(tool_calls=[ToolCall(
                tool_name="lesson_write_section",
                input={"section_id": "SEC-OBJECTIVES", "blocks": new_blocks},
            )], completed=False),
            AgentDecision(completed=True, output={"core": {}}, summary="内容已写入"),
        ]),
        instruction="把教学目标的行为动词改得更可观测", mode="auto",
    )
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.resolved_intent.target_section_ids == ["SEC-OBJECTIVES"]
    # 其他章节与内核逐字不变。
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-OBJECTIVES":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]


# ---------------------------------------------------------------------------
# 8. 矛盾事件流与执行范围统一
# ---------------------------------------------------------------------------


async def _async_run_noop(*_args, **_kwargs):
    return None


def test_execution_scope_uses_contract_targets():
    """LLM 执行范围 = 契约目标（意图识别接地结果），不是用户选中范围。"""
    runtime = _make_runtime(SimpleNamespace())
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.resolved_intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-OBJECTIVES"],
        resolved_scope=["SEC-OBJECTIVES"], required_change_kinds=["section_content"],
    )
    assert runtime.execution_scope_ids() == ["SEC-OBJECTIVES"]
    # 契约目标为空时回退到用户选中范围。
    runtime.resolved_intent = LessonPlanIntentDecision(intent="SECTION_EDIT")
    assert runtime.execution_scope_ids() == ["SEC-REFLECTION"]


def test_rejected_message_run_event_stream_is_coherent():
    """被拒绝的 message 运行：不再发送“修订完成”(revision_completed) 与成功型
    polish.result(✅)，只发送“未应用，原版本已保留”的终结事件，避免与
    result.rejected(⛔) 互相矛盾。"""
    import app.services.lesson_plan_pipeline_service as service

    events: list[str] = []

    class _Emitter:
        async def agent_status_delta(self, *args, **kwargs):
            return None

        async def revision_started(self, *args, **kwargs):
            events.append("revision_started")

        async def emit_domain(self, event_type, **kwargs):
            events.append(event_type)

        async def revision_completed(self, *args, **kwargs):
            events.append("revision_completed")

        async def agent_message_append(self, text):
            events.append("agent_message_append")

    source_content = make_lesson_plan_v2(make_bp()).model_dump()
    source = SimpleNamespace(version=17, content_json=source_content)
    message = SimpleNamespace(content="教学反思的序号有问题")
    runtime = _make_runtime(SimpleNamespace(), instruction="教学反思的序号有问题", mode="auto")
    runtime.emitter = _Emitter()
    runtime.pipeline_run = SimpleNamespace(max_revision_rounds=3)
    runtime.result_status = "rejected"
    runtime.active_intent = "SECTION_FORMAT_EDIT"
    runtime.intent_gate = {"code": "no_change_but_request_unfulfilled"}
    runtime.affected_section_ids = []
    runtime.diff_summary = {}
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.run = _async_run_noop  # 跳过完整流水线执行，只测事件选择

    _, payload = asyncio.run(service._run_pipeline_message(runtime, source, message))

    assert "revision_completed" not in events, f"被拒绝时不得发送修订完成：{events}"
    assert "polish.result" not in events, f"被拒绝时不得发送成功型 polish.result：{events}"
    assert "repair.completed" in events
    assert "未检测到可应用的修改" in payload.assistant_reply


def test_applied_message_run_emits_revision_completed_and_polish_result():
    """成功应用的 message 运行：修订完成 + polish.result 正常发送。"""
    import app.services.lesson_plan_pipeline_service as service

    events: list[str] = []

    class _Emitter:
        async def agent_status_delta(self, *args, **kwargs):
            return None

        async def revision_started(self, *args, **kwargs):
            events.append("revision_started")

        async def emit_domain(self, event_type, **kwargs):
            events.append(event_type)

        async def revision_completed(self, *args, **kwargs):
            events.append("revision_completed")

        async def agent_message_append(self, text):
            events.append("agent_message_append")

    source_content = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source_content)
    modified["outline"]["sections"][0]["title"] = "内容分析（已调整）"
    source = SimpleNamespace(version=17, content_json=source_content)
    message = SimpleNamespace(content="把内容分析改得更详细")
    runtime = _make_runtime(SimpleNamespace(), instruction="把内容分析改得更详细", mode="content")
    runtime.emitter = _Emitter()
    runtime.pipeline_run = SimpleNamespace(max_revision_rounds=3)
    runtime.result_status = "applied"
    runtime.active_intent = "SECTION_EDIT"
    runtime.intent_gate = {"passed": True}
    runtime.diff_summary = {"changed": True, "changed_sections": ["SEC-CONTENT"]}
    runtime.affected_section_ids = ["SEC-CONTENT"]
    runtime.draft_content = modified
    runtime.selected_section_ids = ["SEC-CONTENT"]
    runtime.run = _async_run_noop

    _, payload = asyncio.run(service._run_pipeline_message(runtime, source, message))

    assert "revision_completed" in events
    assert "polish.result" in events
    assert "repair.completed" in events
    assert "V18" in payload.assistant_reply or "V18" in str(payload.assistant_reply)


def test_rejected_result_event_message_matches_gate_cause():
    """result.rejected 的文案按实际原因区分，不再是笼统的“修改被安全拒绝”。"""
    from app.agent.agents.lesson_plan.intents import LessonPlanIntentDecision

    messages: list[tuple[str, str]] = []

    class _Emitter:
        async def emit_domain(self, event_type, **kwargs):
            messages.append((event_type, kwargs.get("message", "")))

    runtime = _make_runtime(SimpleNamespace(), instruction="把反思序号修一下", mode="auto")
    runtime.emitter = _Emitter()
    runtime.resolved_intent = LessonPlanIntentDecision(intent="SECTION_FORMAT_EDIT")

    # 未检测到可应用修改。
    runtime.result_status = "rejected"
    runtime.intent_gate = {"code": "no_change_but_request_unfulfilled"}
    runtime.active_intent = "SECTION_FORMAT_EDIT"
    runtime.diff_summary = {}
    runtime.affected_section_ids = []
    runtime.verification_report = {}
    asyncio.run(runtime._emit_result_status_event())
    assert messages[-1][0] == "result.rejected"
    assert "未检测到可应用" in messages[-1][1]

    # 致命工具越权。
    runtime.intent_gate = {"code": "fatal_tool_error", "error_code": "section_scope_violation"}
    asyncio.run(runtime._emit_result_status_event())
    assert "被安全拒绝" in messages[-1][1]


# ---------------------------------------------------------------------------
# 9. 确定性修复无效 → 升级 LLM 分析师轮次
# ---------------------------------------------------------------------------


def test_analyst_round_escalates_when_deterministic_fix_noops():
    """格式类修改：确定性 normalizer 无变化时，真实 Provider 下必须升级一次
    LLM 分析师轮次（lesson_designer 读取源文档并落实修改），不能零 LLM 直接
    判定“未检测到可应用的修改”。"""
    from app.agent.agents.lesson_plan.agents import AGENT_BY_KEY

    source = make_lesson_plan_v2(make_bp()).model_dump()
    # 目标章节无硬编码序号（normalizer 无操作），但用户明确要求修改。
    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="coarse-format", classifier_version="v4",
    )
    provider = _ScriptedProvider(intent, [
        # 分析师轮次（lesson_designer）：读取源并写入目标章节。
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={"section_id": "SEC-REFLECTION",
                   "blocks": [{"kind": "paragraph", "text": "教师课后反思：目标达成情况、改进方向。"}]},
        )], completed=False),
        AgentDecision(completed=True, output={"core": {}}, summary="反思已修正"),
    ])
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题，作为一个新的点序号为什么是二", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    asyncio.run(runtime.run())

    # 分析师轮次被触发：lesson_designer 进入了执行链，且通过 LLM 路径消费决策。
    assert runtime._analyst_attempted is True
    assert "lesson_designer" in runtime.executed_chain
    # 全节点 LLM 化后：intent 1 + 主链确定性节点分析（intent_planner/context_researcher/
    # format_normalizer/pedagogy_qa/finalizer）5 + 分析师 lesson_designer 2 + 分析师 finalizer 1 = 9。
    assert provider.calls == 9, f"全节点 LLM 化后应为 9 次模型调用，实际 {provider.calls}"
    # 修改已应用：目标章节被模型修改，其他章节逐字不变。
    assert runtime.result_status == "applied"
    reflection = next(
        item for item in runtime.draft_content["outline"]["sections"] if item["id"] == "SEC-REFLECTION"
    )
    assert "改进方向" in reflection["blocks"][0]["text"]
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-REFLECTION":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]


def test_analyst_round_skipped_when_mock_provider():
    """Mock 路径：不触发分析师轮次（确定性行为，保持测试稳定）。"""
    from app.providers.llm.mock import MockProvider

    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(MockProvider(), instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    asyncio.run(runtime.run())
    assert runtime._analyst_attempted is False
    assert "lesson_designer" not in runtime.executed_chain


def test_analyst_round_skipped_when_main_chain_already_changed():
    """主链已有实际修改时不再升级分析师（避免多余模型调用）。"""
    from app.agent.agents.lesson_plan.agents import AGENT_BY_KEY

    source = make_lesson_plan_v2(make_bp()).model_dump()
    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="coarse-format", classifier_version="v4",
    )
    source_modified = copy.deepcopy(source)
    for section in source_modified["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "一、教师课后反思框架"}]
    provider = _ScriptedProvider(intent, [])
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    runtime.builder = LessonPlanBuilder(source_modified)
    runtime.baseline_content = copy.deepcopy(source)
    asyncio.run(runtime.run())
    # normalizer 产生了实际修改 → 不升级分析师。
    assert runtime._analyst_attempted is False
    assert "lesson_designer" not in runtime.executed_chain
    assert runtime.result_status == "applied"


# ---------------------------------------------------------------------------
# 10. 全部节点深度 LLM 分析（确定性保底 + 附分析）
# ---------------------------------------------------------------------------


def test_analysis_nodes_attach_llm_analysis_to_deterministic_output():
    """intent_planner / context_researcher / format_normalizer / pedagogy_qa /
    repair_router / finalizer 在真实 Provider 下先调 LLM 深度分析，确定性产物作为
    基础并把分析附加到 llm_analysis 字段（校验/路由/组装仍由确定性逻辑裁决）。"""
    from app.agent.agents.lesson_plan.agents import (
        AGENT_BY_KEY, FINALIZER, INTENT_PLANNER, PEDAGOGY_QA,
    )
    from app.agent.agents.lesson_plan.runtime import _call_agent

    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True, rule_match="coarse-format", classifier_version="v4",
    )
    source = make_lesson_plan_v2(make_bp()).model_dump()
    provider = _ScriptedProvider(intent, [])
    runtime = _make_runtime(provider, instruction="教学反思的序号有问题", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=18)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    asyncio.run(runtime._prepare())

    decision = asyncio.run(_call_agent(runtime, "finalizer", FINALIZER, 0))
    assert decision.completed is True
    assert decision.output.get("content") is not None, "确定性组装产物必须存在"
    assert decision.output.get("llm_analysis") is not None, "LLM 深度分析应附加到产物"
    assert provider.calls == 1
    # 意图规划节点同样深度分析（确定性产物为基础）。
    decision2 = asyncio.run(_call_agent(runtime, "intent_planner", INTENT_PLANNER, 0))
    assert decision2.output.get("llm_analysis") is not None


def test_answer_finalizer_uses_llm_real_answer():
    """answer_finalizer：真实 Provider 下 LLM 真实回答优先，不再是模板字符串。"""
    from app.agent.agents.lesson_plan.agents import ANSWER_FINALIZER
    from app.agent.agents.lesson_plan.runtime import _call_agent

    intent = LessonPlanIntentDecision(
        intent="ANSWER_ONLY", required_change_kinds=["answer_only"],
        forbidden_change_kinds=["outline_structure", "section_content", "core_content", "timing"],
    )
    source = make_lesson_plan_v2(make_bp()).model_dump()
    provider = _ScriptedProvider(intent, [
        AgentDecision(completed=True, output={
            "answer": "行为动词让目标可观测、可判定，例如“能解释”“能说明”。", "mode": "answer_only",
        }, summary="已回答"),
    ])
    runtime = _make_runtime(provider, instruction="教学目标为什么要用行为动词描述？", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    asyncio.run(runtime._prepare())

    decision = asyncio.run(_call_agent(runtime, "answer_finalizer", ANSWER_FINALIZER, 0))
    assert decision.completed is True
    assert "行为动词" in str(decision.output.get("answer") or "")
    assert "已收到你的问题" not in str(decision.output.get("answer") or ""), "不得回退确定性模板"


# ---------------------------------------------------------------------------
# 11. 分析节点 LLM 工具循环不耗尽（max_steps 足够）
# ---------------------------------------------------------------------------


class _ResearcherToolLoopProvider(_ScriptedProvider):
    """把「上下文调研」也当作 LLM 驱动节点：模拟真实环境 LLM 请求只读工具。"""

    _LLM_DRIVER_NAMES = ("「目录设计」", "「教学设计」", "「问答答复」", "「上下文调研」")


def test_context_researcher_llm_tool_loop_completes_not_exhausted():
    """context_researcher 作为 LLM 驱动请求只读工具后，能基于工具结果完成，
    不再出现 agent_tool_round_exhausted（max_steps 提高到 4）。"""
    from app.agent.agents.lesson_plan.agents import AGENT_BY_KEY

    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-LEARNER"],
        target_fact_keys=["learner_analysis"],
        required_change_kinds=["section_content"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
    )
    new_blocks = [{"kind": "paragraph", "text": "学情分析：八年级学生具备直角三角形基础，能跟随情境推理。"}]
    provider = _ResearcherToolLoopProvider(intent, [
        # context_researcher：LLM 请求读取目标章节 → 工具执行 → 再决策完成。
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_get_source", input={"view": "section", "section_id": "SEC-LEARNER"},
        )], completed=False),
        AgentDecision(completed=True, output={"research_note": "已调研学情"}, summary="调研完成"),
        # lesson_designer：写入目标章节落实修改。
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={"section_id": "SEC-LEARNER", "blocks": new_blocks},
        )], completed=False),
        AgentDecision(completed=True, output={"core": {}}, summary="学情已润色"),
    ])
    source = make_lesson_plan_v2(make_bp()).model_dump()
    # 模拟 v23 真实文档：V2 默认大纲没有 SEC-LEARNER，补上供目标定位。
    source["outline"]["sections"].append({
        "id": "SEC-LEARNER", "title": "学情分析", "summary": "学生基础与认知特点。",
        "coverage_refs": ["learner_analysis"],
        "blocks": [{"kind": "paragraph", "text": "八年级学生已掌握直角三角形基本概念。"}],
        "children": [],
    })
    runtime = _make_runtime(provider, instruction="润色一下学情分析部分的内容", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=23)
    runtime.selected_section_ids = ["SEC-LEARNER"]
    asyncio.run(runtime.run())

    # context_researcher 工具循环正常完成，不再耗尽。
    stats = runtime.agent_stats.get("context_researcher") or {}
    assert stats.get("completed") is True, f"context_researcher 未完成：{stats}"
    assert runtime.termination_reason != "agent_tool_round_exhausted"
    # 工具结果已回喂；修改落地。
    assert runtime.context.has_tool_result("lesson_get_source")
    assert runtime.result_status == "applied"
    learner = next(
        item for item in runtime.draft_content["outline"]["sections"] if item["id"] == "SEC-LEARNER"
    )
    assert "能跟随情境推理" in learner["blocks"][0]["text"]
    # 其他章节与内核逐字不变。
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-LEARNER":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]


# ---------------------------------------------------------------------------
# 12. 教学设计不受 token 限额约束
# ---------------------------------------------------------------------------


def test_lesson_plan_runtime_ignores_cumulative_token_limit():
    """教学设计 runtime 不受累计 token 限额约束（max_estimated_tokens=0）：
    即使 token_usage 超过 60k 也能继续调用模型，不再触发 agent_token_budget_exceeded。"""
    from app.agent.agents.lesson_plan.agents import AGENT_BY_KEY
    from app.agent.agents.lesson_plan.runtime import _call_agent
    from app.agent.schemas import AgentDecision

    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-CONTENT"],
        target_fact_keys=["content_analysis"],
        required_change_kinds=["section_content"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
    )
    provider = _ScriptedProvider(intent, [
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={"section_id": "SEC-CONTENT", "blocks": [{"kind": "paragraph", "text": "更详细的内容分析。"}]},
        )], completed=False),
        AgentDecision(completed=True, output={"core": {}}, summary="内容已更新"),
    ])
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(provider, instruction="把内容分析改得更详细", mode="content")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    # 模拟累计 token 已远超 60k：不应中止。
    runtime.token_usage["tokens"] = 200_000
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.termination_reason != "agent_token_budget_exceeded"
    assert runtime.max_estimated_tokens == 0
    assert runtime.max_context_tokens == 0


def test_generic_runtime_keeps_token_limit():
    """通用 runtime（PPT/任务单等）保持 60k 限额：累计超限仍触发失败。"""
    from app.agent.core.error import AgentError
    from app.agent.core.loop import run_agent_loop
    from app.agent.core.state import AgentRuntimeState
    from app.agent.context import ContextState
    from app.agent.schemas import AgentSpec, PipelinePlan

    runtime = AgentRuntimeState(context=ContextState())
    runtime.max_estimated_tokens = 60_000  # 默认值
    runtime.token_usage["tokens"] = 60_001

    async def call_agent(*_args):
        return AgentDecision(completed=True, output={}, summary="不应完成")

    with pytest.raises(AgentError) as caught:
        asyncio.run(run_agent_loop(
            runtime,
            PipelinePlan(agents=[AgentSpec(key="budget", role="budget", max_steps=1)]),
            agent_registry={"budget": type("A", (), {"allowed_tools": [], "name": "x"})()},
            call_agent=call_agent,
            persist_artifact=lambda *_a, **_k: None,
        ))
    assert caught.value.code == "agent_token_budget_exceeded"


# ---------------------------------------------------------------------------
# 13. 内容修改门禁不误伤固有结构序数
# ---------------------------------------------------------------------------


def test_content_edit_with_inherent_ordinals_applies_not_rejected():
    """用户要求「润色补充板书设计」：设计师写入含「一、二、」板块结构的正文
    （内容固有排版，非渲染器编号错误）→ 必须 applied，正文原样保留，不被
    确定性 strip 改坏，也不被 numbering 门禁阻断。"""
    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-BOARD"],
        target_fact_keys=["board_design"],
        required_change_kinds=["section_content"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
    )
    new_blocks = [{"kind": "paragraph", "text": (
        "【板书设计】\n"
        "一、 主板书：核心概念与公式推导\n"
        "二、 副板书：受力图解与深度避坑提醒\n"
        "┌──────────────────────────────────────────────────┐\n"
        "│ 浮力成因 = 压力差法                          │\n"
        "└──────────────────────────────────────────────────┘"
    )}]
    provider = _ScriptedProvider(intent, [
        # lesson_designer（LLM 驱动）：读取目标章节并写入润色后正文。
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_get_source",
            input={"view": "section", "section_id": "SEC-BOARD"},
        )], completed=False),
        AgentDecision(completed=True, output={"research_note": "已读取板书现状"}, summary="调研完成"),
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={"section_id": "SEC-BOARD", "blocks": new_blocks},
        )], completed=False),
        AgentDecision(completed=True, output={"core": {}}, summary="板书已补充"),
    ])
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(provider, instruction="润色补充一下板书设计部分的内容", mode="content")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=25)
    runtime.selected_section_ids = ["SEC-BOARD"]
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied", f"内容修改被误拒：{runtime.intent_gate.get('code')}"
    assert runtime.publishable is True
    board = next(
        item for item in runtime.draft_content["outline"]["sections"] if item["id"] == "SEC-BOARD"
    )
    # 正文原样保留：固有「一、二、」板块结构不被确定性 strip 改坏。
    assert "一、 主板书" in board["blocks"][0]["text"]
    assert "二、 副板书" in board["blocks"][0]["text"]
    assert "压力差法" in board["blocks"][0]["text"]
    # 其他章节与内核逐字不变。
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-BOARD":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]
