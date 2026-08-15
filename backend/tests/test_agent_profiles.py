import asyncio

import pytest

from app.agents.generators import make_blueprint
from app.models.entities import CourseProject
from app.providers.llm.base import LLMProviderError
from app.schemas.agent_profile import AgentInitializationBundle
from app.services.agent_initialization_service import deterministic_bundle, generate_initialization_bundle
from app.services.agent_prompt_service import (
    OUTPUT_PRESENTATION_RULES,
    apply_output_rules,
    prompt_hash,
    render_template,
)


def test_prompt_renderer_is_deterministic_and_rejects_unknown_tokens():
    rendered = render_template("课程={{course_identity_json}}", {"course_identity_json": "物理"})
    assert rendered == "课程=物理"
    assert prompt_hash("system", rendered) == prompt_hash("system", rendered)
    with pytest.raises(ValueError, match="未知占位符"):
        render_template("{{unsafe_expression}}", {})


def test_apply_output_rules_appends_presentation_constraints():
    system = apply_output_rules("你是教学设计 Agent。")
    assert "输出呈现规范" in system
    assert "禁止输出 HTML 标签源码" in system
    assert "禁止输出连续多个空行" in system
    assert system.endswith(OUTPUT_PRESENTATION_RULES)
    # 幂等：重复注入不会叠加
    assert apply_output_rules(system) == system


def test_mock_initializer_returns_six_distinct_typed_profiles():
    course = CourseProject(
        owner_id="u", title="阿基米德原理", subject="物理", grade_level="八年级",
        audience="八年级学生", duration_minutes=10, scenario="课堂讲解", language="中文",
        settings_json={"style_requirements": "生动、直观"},
    )
    bundle = deterministic_bundle(make_blueprint(course), course, source={
        "confirmed_requirement": {"raw_teacher_intent": "突出浮力来源", "fields": {"duration": 10}},
        "materials": [{"filename": "教材.pdf", "summary": "液体压强与浮力关系"}],
    })
    validated = AgentInitializationBundle.model_validate(bundle.model_dump())
    assert {item.task_type for item in validated.profiles} == {
        "lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim",
    }
    assert len({item.mission for item in validated.profiles}) == 6
    assert all(item.project_requirement_summary for item in validated.profiles)
    assert all(item.material_summaries == ["教材.pdf：液体压强与浮力关系"] for item in validated.profiles)


@pytest.mark.asyncio
async def test_initializer_recovers_from_retryable_provider_failure_without_generic_profiles():
    class TemporarilyUnavailableProvider:
        async def structured(self, system, prompt, schema):
            assert "输出 JSON Schema" not in prompt
            raise LLMProviderError(
                code="upstream_http_error",
                user_message="模型服务返回 HTTP 503。",
                retryable=True,
                status_code=503,
            )

    course = CourseProject(
        id="course-1", owner_id="u", title="阿基米德原理", subject="物理", grade_level="八年级",
        audience="八年级学生", duration_minutes=10, scenario="课堂讲解", language="中文",
        settings_json={"style_requirements": "生动、直观"},
    )
    blueprint = make_blueprint(course)
    bundle, warning = await generate_initialization_bundle(
        TemporarilyUnavailableProvider(), blueprint, course, {"course": {"title": course.title}}, {},
    )

    assert warning and warning["code"] == "model_extraction_temporarily_unavailable"
    assert len(bundle.profiles) == 6
    assert len({item.mission for item in bundle.profiles}) == 6


def test_ppt_profile_has_seven_requirement_groups():
    course = CourseProject(
        owner_id="u", title="牛顿第二定律", subject="高中物理", grade_level="高一",
        audience="已学习运动学基础的学生", duration_minutes=15, scenario="课堂讲解",
        language="中文", settings_json={},
    )
    bundle = deterministic_bundle(make_blueprint(course), course, source={})
    ppt = next(profile for profile in bundle.profiles if profile.task_type == "ppt")
    for field in (
        "narrative_requirements", "visual_hierarchy_requirements",
        "information_density_requirements", "animation_and_diagram_requirements",
        "layout_requirements", "typography_requirements", "visual_suggestion_requirements",
    ):
        assert getattr(ppt, field), f"{field} 为空"
    assert any("版式库" in item for item in ppt.layout_requirements)
    assert any("图形类型" in item for item in ppt.visual_suggestion_requirements)


@pytest.mark.asyncio
async def test_initializer_recovers_from_model_content_errors_with_deterministic_bundle():
    """模型输出截断/非法 JSON/结构不完整：初始化回退到蓝图驱动的确定性配置，而不是失败。"""

    class TruncatedOutputProvider:
        async def structured(self, system, prompt, schema):
            raise LLMProviderError(
                code="upstream_invalid_json",
                user_message="模型返回的内容不是有效 JSON。",
                retryable=False,
            )

    class SchemaMismatchProvider:
        async def structured(self, system, prompt, schema):
            raise LLMProviderError(
                code="upstream_schema_mismatch",
                user_message="结构不完整。",
                retryable=False,
            )

    course = CourseProject(
        id="course-2", owner_id="u", title="阿基米德原理", subject="物理", grade_level="八年级",
        audience="八年级学生", duration_minutes=10, scenario="课堂讲解", language="中文",
        settings_json={},
    )
    for provider in (TruncatedOutputProvider(), SchemaMismatchProvider()):
        bundle, warning = await generate_initialization_bundle(
            provider, make_blueprint(course), course, {"course": {"title": course.title}}, {},
        )
        assert warning and warning["code"] == "model_extraction_temporarily_unavailable"
        assert len(bundle.profiles) == 6
        assert len({item.mission for item in bundle.profiles}) == 6


@pytest.mark.asyncio
async def test_initializer_still_raises_on_hard_failures():
    """认证/HTTP 等硬失败仍应报错，不掩盖模型配置问题。"""

    class HardFailureProvider:
        async def structured(self, system, prompt, schema):
            raise LLMProviderError(
                code="upstream_http_error",
                user_message="模型服务返回 HTTP 401（API Key 无效）。",
                retryable=False,
                status_code=401,
            )

    course = CourseProject(
        id="course-3", owner_id="u", title="浮力", subject="物理", grade_level="八年级",
        audience="八年级学生", duration_minutes=10, scenario="课堂讲解", language="中文",
        settings_json={},
    )
    with pytest.raises(LLMProviderError, match="HTTP 401"):
        await generate_initialization_bundle(
            HardFailureProvider(), make_blueprint(course), course, {"course": {"title": course.title}}, {},
        )


async def wait_for_project(client, headers, course_id, predicate, attempts=300):
    payload = None
    for _ in range(attempts):
        response = await client.get(f"/api/v1/courses/{course_id}/project", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        await asyncio.sleep(0.02)
    return payload


@pytest.mark.asyncio
async def test_profiles_gate_generation_are_traceable_and_version_on_context_change(client, auth_headers):
    await client.post(
        "/api/v1/settings/models", headers=auth_headers,
        json={
            "name": "Profile Mock", "provider": "mock", "base_url": "mock://profiles",
            "model_name": "mock-profiles", "timeout_seconds": 30, "is_active": True,
        },
    )
    course = (await client.post(
        "/api/v1/courses", headers=auth_headers,
        json={
            "title": "浮力", "subject": "物理", "grade_level": "八年级",
            "audience": "刚接触力学的八年级学生", "duration_minutes": 10,
            "scenario": "课堂讲解", "course_task": "解释浮力来源并完成基础判断",
            "style_requirements": "生动、直观",
        },
    )).json()
    blueprint = (await client.post(
        f"/api/v1/courses/{course['id']}/blueprint/generate", headers=auth_headers,
    )).json()
    before = await client.get(f"/api/v1/courses/{course['id']}/artifacts", headers=auth_headers)
    assert before.json() == []

    approved = await client.post(f"/api/v1/blueprints/{blueprint['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    project = await wait_for_project(
        client, auth_headers, course["id"],
        lambda item: item["agent_initialization"]["status"] == "ready"
        and all(task["current_artifact"] for task in item["tasks"] if task["task_type"] != "video_generation")
        and next(task for task in item["tasks"] if task["task_type"] == "video_generation")["status"] == "waiting_dependency",
    )
    assert project["agent_initialization"]["version"] == 1
    assert all(task["agent_profile_status"] == "ready" for task in project["tasks"])
    content_agent_tasks = [task for task in project["tasks"] if task["task_type"] != "video_generation"]
    assert all(task["agent_profile_summary"]["mission"] for task in content_agent_tasks)
    video_generation = next(task for task in project["tasks"] if task["task_type"] == "video_generation")
    assert video_generation["agent_profile_summary"] is None
    assert video_generation["agent_profile_version"] == 0
    video_task = next(task for task in project["tasks"] if task["task_type"] == "video_script")
    # 共享项目记忆架构：video_script 不再有硬依赖（教学设计为可选参考，不阻塞启动）。
    # 并行首稿时教学设计可能尚未生成，source_versions 记录"实际读取"的版本（可为空）。
    assert video_task["dependency_types"] == []
    assert video_task["optional_reference_types"] == ["lesson_plan"]
    assert video_task["current_artifact"]["content_json"]["schema_version"] == "3.0"
    assert video_task["current_artifact"]["prompt_version"] == "v3"
    artifacts = (await client.get(
        f"/api/v1/courses/{course['id']}/artifacts", headers=auth_headers,
    )).json()
    task_artifacts = [item for item in artifacts if item["artifact_type"] in {
        "lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim",
    }]
    assert len(task_artifacts) == 6
    assert all(item["agent_profile_id"] for item in task_artifacts)

    repeated = await client.post(
        f"/api/v1/courses/{course['id']}/agent-initialization/runs", headers=auth_headers,
    )
    assert repeated.status_code == 202
    assert repeated.json()["created"] is False

    changed = await client.patch(
        f"/api/v1/courses/{course['id']}", headers=auth_headers,
        json={"audience": "需要更多视觉支架的八年级学生"},
    )
    assert changed.status_code == 200, changed.text
    project = await wait_for_project(
        client, auth_headers, course["id"],
        lambda item: item["agent_initialization"]["version"] == 2
        and all(task["stale_agent_profile"] for task in item["tasks"]),
    )
    lesson = next(task for task in project["tasks"] if task["task_type"] == "lesson_plan")
    assert lesson["agent_profile_summary"]["audience"] == "需要更多视觉支架的八年级学生"
    # 项目背景变化后：同步项目上下文（走通用分发，兼容旧客户端 action），
    # 使用当前专属配置重新生成候选稿，stale_agent_profile 应清除。
    synced = await client.post(
        f"/api/v1/courses/{course['id']}/tasks/lesson_plan/runs", headers=auth_headers,
        json={"action": "sync_context"},
    )
    assert synced.status_code == 202, synced.text
    project = await wait_for_project(
        client, auth_headers, course["id"],
        lambda item: next(task for task in item["tasks"] if task["task_type"] == "lesson_plan")["current_artifact"]["version"] == 2,
    )
    lesson = next(task for task in project["tasks"] if task["task_type"] == "lesson_plan")
    assert lesson["stale_agent_profile"] is False
