from copy import deepcopy
from pathlib import Path

import pytest
from pptx import Presentation
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseProject, CourseTask
from app.services.ppt_template_service import (
    DEFAULT_PPT_TEMPLATE_ID,
    get_ppt_template,
    load_ppt_template_catalog,
)


def sample_ppt_content(theme=DEFAULT_PPT_TEMPLATE_ID):
    return {
        "theme": theme,
        "slides": [
            {
                "id": "S01", "page_type": "cover", "title": "阿基米德原理",
                "purpose": "建立课程主题", "body": ["物理", "八年级"], "layout": "title",
                "visual_suggestion": "使用简洁几何构图", "speaker_notes": "说明本课问题。",
                "duration_seconds": 20,
            },
            {
                "id": "S02", "page_type": "concept", "title": "浮力从哪里来",
                "purpose": "建立准确理解", "body": ["上、下表面存在压力差"], "layout": "split",
                "visual_suggestion": "左右对照压力方向", "speaker_notes": "讲解压力差。",
                "duration_seconds": 60,
            },
        ],
    }


def test_template_catalog_has_twelve_valid_unique_templates():
    catalog = load_ppt_template_catalog()
    assert catalog["version"]
    assert len(catalog["templates"]) == 12
    ids = [item["id"] for item in catalog["templates"]]
    assert len(set(ids)) == 12
    assert get_ppt_template(DEFAULT_PPT_TEMPLATE_ID)
    assert all(len(item["recommended_for"]) == 3 for item in catalog["templates"])
    template_dir = Path(__file__).resolve().parents[2] / "templates" / "pptx"
    for item in catalog["templates"]:
        template_path = template_dir / item["file"]
        assert template_path.is_file()
        deck = Presentation(template_path)
        expected_slides = 15 if item["composition"] == "deck" else 6
        assert len(deck.slides) == expected_slides
        assert deck.slide_width / deck.slide_height == pytest.approx(16 / 9, rel=0.01)


@pytest.mark.asyncio
async def test_apply_template_creates_visual_only_version_without_staling_dependents(client, auth_headers):
    user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    original_content = sample_ppt_content()
    async with SessionLocal() as db:
        course = CourseProject(
            owner_id=user["id"], title="阿基米德原理", subject="物理", grade_level="八年级",
            audience="初中学生", duration_minutes=10, scenario="课堂讲解", settings_json={},
        )
        db.add(course)
        await db.flush()
        ppt = Artifact(
            course_id=course.id, artifact_type="ppt", version=1, blueprint_version=1,
            content_json=deepcopy(original_content), content_markdown="# 阿基米德原理", status="draft",
        )
        video = Artifact(
            course_id=course.id, artifact_type="video_script", version=1, blueprint_version=1,
            content_json={"schema_version": "2.0"}, content_markdown="# 视频脚本", status="draft",
            source_versions_json={"lesson_plan": 1, "ppt": 1},
        )
        verbatim = Artifact(
            course_id=course.id, artifact_type="verbatim", version=1, blueprint_version=1,
            content_json={"sections": []}, content_markdown="# 逐字稿", status="draft",
            source_versions_json={"ppt": 1, "video_script": 1},
        )
        db.add_all([ppt, video, verbatim])
        await db.flush()
        ppt_task = CourseTask(
            course_id=course.id, task_type="ppt", agent_type="ppt_agent", display_order=2,
            status="review", progress=100, dependency_types_json=[], current_artifact_id=ppt.id,
        )
        video_task = CourseTask(
            course_id=course.id, task_type="video_script", agent_type="video_script_agent", display_order=5,
            status="review", progress=100, dependency_types_json=["lesson_plan", "ppt"], current_artifact_id=video.id,
        )
        verbatim_task = CourseTask(
            course_id=course.id, task_type="verbatim", agent_type="verbatim_agent", display_order=6,
            status="review", progress=100, dependency_types_json=["ppt", "video_script"], current_artifact_id=verbatim.id,
        )
        db.add_all([ppt_task, video_task, verbatim_task])
        await db.commit()
        ppt_id = ppt.id
        course_id = course.id

    response = await client.post(
        f"/api/v1/artifacts/{ppt_id}/apply-template",
        headers=auth_headers,
        json={"template_id": "lessonforge_science_dark", "expected_version": 1},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changed"] is True
    assert result["artifact"]["version"] == 2
    assert result["artifact"]["content_json"] == {
        **original_content, "theme": "lessonforge_science_dark",
    }
    assert result["artifact"]["change_summary"] == "切换 PPT 模板：深海科技·实验演示"

    async with SessionLocal() as db:
        tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
        statuses = {item.task_type: item.status for item in tasks}
        assert statuses == {"ppt": "review", "video_script": "review", "verbatim": "review"}

    repeated = await client.post(
        f"/api/v1/artifacts/{result['artifact']['id']}/apply-template",
        headers=auth_headers,
        json={"template_id": "lessonforge_science_dark", "expected_version": 2},
    )
    assert repeated.status_code == 200
    assert repeated.json()["changed"] is False

    invalid = await client.post(
        f"/api/v1/artifacts/{result['artifact']['id']}/apply-template",
        headers=auth_headers,
        json={"template_id": "unknown-template", "expected_version": 2},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_template_catalog_endpoint_and_preference_validation(client, auth_headers):
    catalog = await client.get("/api/v1/ppt-templates", headers=auth_headers)
    assert catalog.status_code == 200
    assert len(catalog.json()["templates"]) == 12

    invalid = await client.patch(
        "/api/v1/settings/preferences",
        headers=auth_headers,
        json={
            "default_language": "zh-CN",
            "default_grade_level": "junior_high",
            "default_ppt_template": "missing",
        },
    )
    assert invalid.status_code == 422
