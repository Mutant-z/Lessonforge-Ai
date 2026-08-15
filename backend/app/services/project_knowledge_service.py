"""共享项目记忆服务（ProjectMemoryService）。

把需求、蓝图、材料、Artifact、教师决策、QA 结论和关键对话摘要统一索引进
`project_memory_items`，并以单调递增 revision 追踪变更。六类内容 Agent 不再
通过依赖拓扑阻塞启动：每次运行读取一个项目记忆快照，工作中可按需读取其他
Agent 的最新产物；一个 Agent 修改后不自动重跑其他 Agent。

原始文件和完整 Artifact 仍保留在各自表中，记忆只存结构化摘要与引用路径。
本文件同时保留 `build_project_knowledge_context` 作为快照构建函数，供各
Agent pipeline 服务继续使用（新增 memory_revision / available_sources /
missing_optional_sources 等字段，并保持 sibling_artifacts / hard_dependencies
的既有形状，读者如 _lesson_plan_raw / _video_script_raw 不受影响）。
"""
import json
from typing import Any

from sqlalchemy import func, select

from app.models.entities import (
    Artifact,
    CourseBlueprint,
    CourseProject,
    CourseRequirement,
    CourseTask,
    Material,
    ProjectMemoryItem,
    ProjectMemoryRevision,
)


TASK_PRIORITY = {
    "lesson_plan": ["task_sheet", "ppt", "exercise", "video_script", "verbatim"],
    "ppt": ["lesson_plan", "task_sheet", "video_script", "verbatim", "exercise"],
    "task_sheet": ["lesson_plan", "ppt", "exercise", "video_script", "verbatim"],
    "exercise": ["lesson_plan", "task_sheet", "ppt", "video_script", "verbatim"],
    "video_script": ["lesson_plan"],
    "verbatim": ["video_script"],
}

CONTENT_ARTIFACT_TYPES = ("lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim")

TRUST_LEVELS = {
    "teacher_requirement": "teacher_requirement",
    "blueprint": "approved_blueprint",
    "material": "uploaded_material",
    "artifact": "agent_generated",
    "decision": "teacher_decision",
    "qa": "qa_result",
    "dialogue": "dialogue_summary",
}


def _select_fields(artifact_type: str, content: dict[str, Any]) -> dict[str, Any]:
    if artifact_type == "task_sheet" and content.get("schema_version") == "3.0":
        # V3：动态目录任务单，投影目标目录与章节摘要（学习任务用时、目标覆盖）。
        sections = content.get("sections", [])
        tasks = [
            block for section in sections
            for block in section.get("blocks", [])
            if block.get("kind") == "learning_task"
        ]
        return {
            "schema_version": "3.0",
            "course_info": content.get("course_info"),
            "objective_catalog": content.get("objective_catalog", []),
            "section_count": len(sections),
            "section_titles": [item.get("title") for item in sections],
            "task_count": len(tasks),
            "task_minutes": round(sum(float(t.get("estimated_minutes", 0)) for t in tasks), 1),
        }
    if artifact_type == "lesson_plan":
        # 下游（PPT/任务单/练习/视频脚本）只读稳定教学内核，不读 V2 展示目录；
        # lesson_plan_core() 对 V1/V2 统一投影。
        from app.schemas.lesson_plan import lesson_plan_core

        return lesson_plan_core(content)
    fields = {
        "ppt": ("theme", "slides"),
        "task_sheet": ("schema_version", "learning_objectives", "tasks", "record_table", "learning_questions", "self_assessment", "extension"),
        "exercise": ("schema_version", "course_info", "paper_settings", "sections", "items"),
        "video_script": ("schema_version", "course_info", "production_settings", "scenes", "segments"),
        "verbatim": ("speaking_rate", "sections"),
    }.get(artifact_type, tuple(content.keys()))
    return {field: content[field] for field in fields if field in content}


def _compact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:597] + "..."
    if isinstance(value, list):
        limit = 16 if depth < 2 else 8
        items = [_compact(item, depth + 1) for item in value[:limit]]
        if len(value) > limit:
            items.append({"truncated_items": len(value) - limit})
        return items
    if isinstance(value, dict):
        return {str(key): _compact(item, depth + 1) for key, item in value.items()}
    return value


def _bounded(value: dict[str, Any], limit: int) -> dict[str, Any]:
    compacted = _compact(value)
    serialized = json.dumps(compacted, ensure_ascii=False)
    if len(serialized) <= limit:
        return compacted
    return {"truncated": True, "content_excerpt": serialized[: max(0, limit - 80)]}


def _reference_conflicts(value: Any, blueprint: dict[str, Any], path: str = "$") -> list[str]:
    valid = {
        "objective": {item.get("id") for item in blueprint.get("objectives", [])},
        "knowledge_point": {item.get("id") for item in blueprint.get("knowledge_points", [])},
        "stage": {item.get("segment_id") for item in blueprint.get("timeline", [])},
    }
    conflicts: list[str] = []

    def visit(item: Any, current_path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{current_path}.{key}"
                reference_type = None
                if key in {"objective_id", "objective_ids"}:
                    reference_type = "objective"
                elif key in {"knowledge_point_id", "knowledge_point_ids"}:
                    reference_type = "knowledge_point"
                elif key == "stage_id":
                    reference_type = "stage"
                if reference_type:
                    references = child if isinstance(child, list) else [child]
                    for reference in references:
                        if reference and reference not in valid[reference_type]:
                            conflicts.append(f"{child_path} 引用了蓝图中不存在的 {reference}")
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{current_path}[{index}]")

    visit(value, path)
    return conflicts[:20]


# ---------------------------------------------------------------------------
# 记忆版本管理
# ---------------------------------------------------------------------------


async def current_revision(db, course_id: str) -> int:
    value = await db.scalar(select(func.max(ProjectMemoryRevision.revision)).where(
        ProjectMemoryRevision.course_id == course_id,
    ))
    return int(value or 0)


async def bump(
    db,
    course_id: str,
    reason: str,
    source_type: str = "",
    source_id: str | None = None,
    created_by: str = "system",
) -> int:
    """在同一事务内推进项目记忆版本，返回新 revision。"""
    next_revision = (await current_revision(db, course_id)) + 1
    db.add(ProjectMemoryRevision(
        course_id=course_id, revision=next_revision, change_reason=reason[:300],
        source_type=source_type, source_id=source_id, created_by=created_by,
    ))
    return next_revision


async def _upsert_item(
    db,
    course_id: str,
    source_type: str,
    source_id: str,
    *,
    revision: int,
    source_version: int = 0,
    artifact_type: str = "",
    summary: dict[str, Any] | None = None,
    content_ref: str = "",
    keywords: list[str] | None = None,
    trust_level: str | None = None,
    created_by: str = "system",
) -> None:
    item = await db.scalar(select(ProjectMemoryItem).where(
        ProjectMemoryItem.course_id == course_id,
        ProjectMemoryItem.source_type == source_type,
        ProjectMemoryItem.source_id == source_id,
    ))
    if item is None:
        item = ProjectMemoryItem(
            course_id=course_id, source_type=source_type, source_id=source_id,
        )
        db.add(item)
    item.source_version = source_version
    item.artifact_type = artifact_type
    item.summary_json = summary or {}
    item.content_ref = content_ref
    item.keywords_json = keywords or []
    item.trust_level = trust_level or TRUST_LEVELS.get(source_type, "agent_generated")
    item.memory_revision = revision
    item.created_by = created_by


def _keyword_text(item: Any, *fields: str) -> str:
    """Extract a short keyword from both current object-shaped and legacy values."""
    if isinstance(item, dict):
        for field in fields:
            value = item.get(field)
            if value:
                return str(value)[:40]
        return ""
    return str(item or "")[:40]


def _artifact_keywords(artifact_type: str, summary: dict[str, Any]) -> list[str]:
    keywords: list[str] = [artifact_type]
    if artifact_type == "lesson_plan":
        for objective in summary.get("objectives", [])[:8]:
            keywords.append(_keyword_text(objective, "statement", "behavior"))
        for stage in summary.get("stages", [])[:8]:
            keywords.append(_keyword_text(stage, "name", "title"))
    elif artifact_type == "ppt":
        for slide in summary.get("slides", [])[:12]:
            keywords.append(_keyword_text(slide, "title"))
    elif artifact_type == "video_script":
        for scene in summary.get("scenes", [])[:12]:
            keywords.append(_keyword_text(scene, "title"))
    elif artifact_type == "task_sheet":
        keywords.extend(_keyword_text(item, "title", "statement") for item in summary.get("objective_catalog", [])[:8])
    elif artifact_type == "verbatim":
        for section in summary.get("sections", [])[:8]:
            keywords.append(_keyword_text(section, "required_text", "title"))
    return [keyword for keyword in keywords if keyword.strip()]


# ---------------------------------------------------------------------------
# 各类来源索引（调用方必须与 bump 在同一事务内，先 index 后 bump）
# ---------------------------------------------------------------------------


async def index_artifact(db, artifact: Artifact, created_by: str = "system") -> None:
    """索引一个 Artifact 版本到项目记忆（摘要 + 关键词 + 引用路径）。"""
    if artifact.artifact_type not in CONTENT_ARTIFACT_TYPES:
        return
    summary = _select_fields(artifact.artifact_type, artifact.content_json or {})
    revision = await current_revision(db, artifact.course_id)
    await _upsert_item(
        db, artifact.course_id, "artifact", artifact.id,
        revision=revision, source_version=artifact.version,
        artifact_type=artifact.artifact_type, summary=summary,
        content_ref=f"artifact:{artifact.id}",
        keywords=_artifact_keywords(artifact.artifact_type, summary),
        trust_level="agent_generated", created_by=created_by,
    )


async def index_blueprint(db, blueprint: CourseBlueprint, created_by: str = "system") -> None:
    content = blueprint.content_json or {}
    summary = {
        key: content.get(key)
        for key in ("course_identity", "objectives", "knowledge_points", "timeline", "assessment_plan")
        if key in content
    }
    keywords = [
        str(content.get("course_identity", {}).get("title", ""))[:60],
        *[str(item.get("name") or "")[:40] for item in content.get("knowledge_points", [])[:8]],
    ]
    await _upsert_item(
        db, blueprint.course_id, "blueprint", blueprint.id,
        revision=await current_revision(db, blueprint.course_id),
        source_version=blueprint.version, summary=summary,
        content_ref=f"blueprint:{blueprint.id}",
        keywords=[keyword for keyword in keywords if keyword.strip()],
        trust_level="approved_blueprint", created_by=created_by,
    )


async def index_requirement(db, requirement: CourseRequirement, created_by: str = "system") -> None:
    keywords = [
        str(requirement.raw_prompt or "")[:200],
        *[str(item.get("field") or "")[:40] for item in requirement.assumptions_json or []],
    ]
    await _upsert_item(
        db, requirement.course_id, "requirement", requirement.id,
        revision=await current_revision(db, requirement.course_id),
        source_version=requirement.version,
        summary={
            "fields": requirement.form_json,
            "raw_prompt": (requirement.raw_prompt or "")[:1200],
            "assumptions": requirement.assumptions_json,
            "conflicts": requirement.conflicts_json,
        },
        content_ref=f"requirement:{requirement.id}",
        keywords=[keyword for keyword in keywords if keyword.strip()],
        trust_level="teacher_requirement", created_by=created_by,
    )


async def index_material(db, material: Material, created_by: str = "system") -> None:
    await _upsert_item(
        db, material.course_id, "material", material.id,
        revision=await current_revision(db, material.course_id),
        summary={
            "original_filename": material.original_filename,
            "mime_type": material.mime_type,
            "summary": material.summary,
            "usage_policy": material.usage_policy,
        },
        content_ref=f"material:{material.id}",
        keywords=[material.original_filename[:80], material.summary[:200]],
        trust_level="uploaded_material", created_by=created_by,
    )


async def index_decision(
    db, course_id: str, decision_id: str, title: str, detail: str,
    *, created_by: str = "system", summary: dict[str, Any] | None = None,
) -> None:
    await _upsert_item(
        db, course_id, "decision", decision_id,
        revision=await current_revision(db, course_id),
        summary=summary or {"title": title[:200], "detail": detail[:800]},
        content_ref=f"decision:{decision_id}",
        keywords=[title[:100]],
        trust_level="teacher_decision", created_by=created_by,
    )


async def index_qa(
    db, course_id: str, report_id: str, score: int, summary_text: str,
    issues: list[dict[str, Any]] | None = None, *, created_by: str = "system",
) -> None:
    issues = issues or []
    await _upsert_item(
        db, course_id, "qa", report_id,
        revision=await current_revision(db, course_id),
        summary={"score": score, "summary": summary_text[:600], "issue_count": len(issues)},
        content_ref=f"qa:{report_id}",
        keywords=[f"QA {score}", *[str(item.get("description") or "")[:60] for item in issues[:6]]],
        trust_level="qa_result", created_by=created_by,
    )


# ---------------------------------------------------------------------------
# 只读回填（幂等 upsert，不推进 revision）
# ---------------------------------------------------------------------------


async def ensure_initialized(db, course_id: str) -> int:
    """把存量需求/蓝图/材料/Artifact 索引进项目记忆（幂等），返回当前 revision。"""
    course = await db.get(CourseProject, course_id)
    if not course:
        return 0
    requirement = await db.scalar(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id,
    ).order_by(CourseRequirement.version.desc()))
    if requirement:
        await index_requirement(db, requirement, created_by="backfill")
    blueprint = await db.scalar(select(CourseBlueprint).where(
        CourseBlueprint.course_id == course_id,
    ).order_by(CourseBlueprint.version.desc()))
    if blueprint:
        await index_blueprint(db, blueprint, created_by="backfill")
    for material in list(await db.scalars(select(Material).where(
        Material.course_id == course_id,
    ))):
        await index_material(db, material, created_by="backfill")
    for artifact in list(await db.scalars(select(Artifact).where(
        Artifact.course_id == course_id,
        Artifact.artifact_type.in_(CONTENT_ARTIFACT_TYPES),
    ))):
        await index_artifact(db, artifact, created_by="backfill")
    return await current_revision(db, course_id)


# ---------------------------------------------------------------------------
# 查询（API / 前端面板）
# ---------------------------------------------------------------------------


def serialize_item(item: ProjectMemoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "course_id": item.course_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "source_version": item.source_version,
        "artifact_type": item.artifact_type,
        "summary": item.summary_json,
        "content_ref": item.content_ref,
        "keywords": item.keywords_json,
        "trust_level": item.trust_level,
        "memory_revision": item.memory_revision,
        "created_by": item.created_by,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def list_items(db, course_id: str, limit: int = 200) -> list[ProjectMemoryItem]:
    return list(await db.scalars(
        select(ProjectMemoryItem).where(ProjectMemoryItem.course_id == course_id)
        .order_by(ProjectMemoryItem.updated_at.desc()).limit(limit)
    ))


async def get_item(db, course_id: str, item_id: str) -> ProjectMemoryItem | None:
    return await db.scalar(select(ProjectMemoryItem).where(
        ProjectMemoryItem.course_id == course_id,
        ProjectMemoryItem.id == item_id,
    ))


async def search_items(db, course_id: str, query: str, limit: int = 50) -> list[ProjectMemoryItem]:
    lowered = query.strip().lower()
    if not lowered:
        return []
    items = await list_items(db, course_id, limit=500)
    matched: list[ProjectMemoryItem] = []
    for item in items:
        haystack = " ".join([
            item.source_type, item.artifact_type, item.content_ref,
            json.dumps(item.summary_json, ensure_ascii=False),
            " ".join(item.keywords_json or []),
        ]).lower()
        if lowered in haystack:
            matched.append(item)
        if len(matched) >= limit:
            break
    return matched


# ---------------------------------------------------------------------------
# 上下文快照
# ---------------------------------------------------------------------------


async def build_project_knowledge_context(
    db,
    task: CourseTask,
    blueprint: dict[str, Any],
    blueprint_version: int,
    profile_context: dict[str, Any],
    context_window_tokens: int | None,
    run=None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Build a bounded, course-isolated snapshot of the shared project memory.

    保持既有 sibling_artifacts / hard_dependencies / blueprint 形状，供各
    pipeline 与 Agent 读取工具继续使用；新增 memory_revision /
    available_sources / missing_optional_sources / decisions / qa_findings。
    """
    declared_window = context_window_tokens or 100_000
    total_budget = max(512, min(24_000, int(declared_window * 0.20)))
    blueprint_summary = {
        key: blueprint.get(key)
        for key in ("course_identity", "objectives", "knowledge_points", "timeline", "assessment_plan")
        if key in blueprint
    }
    context: dict[str, Any] = {
        "authority_order": [
            "system_schema_and_locks",
            "approved_blueprint",
            "teacher_instruction",
            "current_target_artifact",
            "project_memory_references",
        ],
        "memory_revision": await current_revision(db, task.course_id),
        "blueprint": {"version": blueprint_version, "summary": _bounded(blueprint_summary, min(8_000, total_budget // 3))},
        "agent_profile_summary": {
            key: profile_context.get(key)
            for key in (
                "project_background", "project_requirement_summary", "learner_profile",
                "content_scope", "required_source_refs", "material_summaries",
            )
            if profile_context.get(key)
        },
        "hard_dependencies": {},
        "sibling_artifacts": {},
        "available_sources": {},
        "missing_optional_sources": [],
        "decisions": [],
        "qa_findings": [],
        "conflicts": [],
    }
    tasks = list(await db.scalars(select(CourseTask).where(
        CourseTask.course_id == task.course_id,
    )))
    by_type = {item.task_type: item for item in tasks if item.task_type != task.task_type}
    remaining = max(0, total_budget - len(json.dumps(context, ensure_ascii=False)))
    source_versions: dict[str, int] = {}
    for artifact_type in TASK_PRIORITY.get(task.task_type, list(by_type)):
        sibling = by_type.get(artifact_type)
        if not sibling or not sibling.current_artifact_id or remaining < 256:
            continue
        artifact = await db.scalar(select(Artifact).where(
            Artifact.id == sibling.current_artifact_id,
            Artifact.course_id == task.course_id,
            Artifact.artifact_type == artifact_type,
        ))
        if not artifact:
            continue
        allowance = min(5_000, remaining)
        selected = _bounded(_select_fields(artifact_type, artifact.content_json or {}), allowance)
        entry = {"version": artifact.version, "status": artifact.status, "content": selected}
        # 旧读者（_lesson_plan_raw 等）同时兼容 hard_dependencies 与 sibling_artifacts。
        context["sibling_artifacts"][artifact_type] = entry
        if artifact_type in (task.dependency_types_json or []):
            context["hard_dependencies"][artifact_type] = entry
        context["available_sources"][artifact_type] = {
            "version": artifact.version, "status": artifact.status, "available": True,
        }
        context["conflicts"].extend(
            f"{artifact_type} V{artifact.version}：{item}"
            for item in _reference_conflicts(selected, blueprint)
        )
        source_versions[artifact_type] = artifact.version
        remaining -= len(json.dumps({artifact_type: entry}, ensure_ascii=False))
    for reference_type in (task.optional_reference_types_json or []):
        if reference_type not in context["available_sources"]:
            context["missing_optional_sources"].append(reference_type)
    # 教师决策与 QA 结论来自项目记忆（受限预算内）。
    memory_items = list(await db.scalars(select(ProjectMemoryItem).where(
        ProjectMemoryItem.course_id == task.course_id,
        ProjectMemoryItem.source_type.in_(("decision", "qa")),
    ).order_by(ProjectMemoryItem.updated_at.desc()).limit(12)))
    decisions: list[dict[str, Any]] = []
    qa_findings: list[dict[str, Any]] = []
    for item in memory_items:
        entry = {"memory_revision": item.memory_revision, **item.summary_json}
        if item.source_type == "decision":
            decisions.append(entry)
        else:
            qa_findings.append(entry)
    context["decisions"] = decisions
    context["qa_findings"] = qa_findings
    if run is not None:
        manifest = {
            "memory_revision": context["memory_revision"],
            "available_sources": context["available_sources"],
            "missing_optional_sources": context["missing_optional_sources"],
            "decisions": decisions,
            "qa_findings": qa_findings,
        }
        run.memory_revision = context["memory_revision"]
        run.context_manifest_json = manifest
        run.context_hash = _snapshot_hash(context)
        task.last_context_revision = context["memory_revision"]
    return context, source_versions


def _snapshot_hash(context: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps({
        "memory_revision": context.get("memory_revision", 0),
        "available_sources": context.get("available_sources", {}),
        "missing_optional_sources": context.get("missing_optional_sources", []),
    }, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
