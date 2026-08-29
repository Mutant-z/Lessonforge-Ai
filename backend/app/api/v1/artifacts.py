from datetime import datetime, timezone
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import get_db
from app.models.entities import AgentChatSession, AgentMessage, Artifact, ArtifactAsset, ArtifactLock, CourseBlueprint, CourseTask, CourseTaskAgentProfile, User
from app.providers.llm.mock import MockProvider
from app.schemas.artifact import (
    AgentArtifactRevision,
    AgentChatModelUpdate,
    ArtifactUpdate,
    CitationReportContent,
    ExerciseContent,
    LessonPlanContent,
    LockRequest,
    PPTContent,
    PPTTemplateApplyRequest,
    QualityReportContent,
    RegenerateRequest,
    TaskSheetContent,
    VerbatimContent,
    VideoScriptContent,
    SeedanceVideoScriptContent,
)
from app.services.model_config_service import owned_model_config, resolve_provider, resolved_model_name
from app.services.course_task_service import is_publishable_video_artifact, register_artifact_version
from app.services.agent_prompt_service import build_runtime_prompts
from app.agents.generators import make_exercises, make_task_sheet, to_markdown
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.quality_service import validate_exercise, validate_video_script
from app.services.ppt_template_service import get_ppt_template, resolve_ppt_template
from app.schemas.video import (
    SeedanceVideoGenerationContent,
    VideoGenerationContent,
    seedance_video_generation_markdown,
    video_generation_markdown,
)

router = APIRouter(tags=["课程资源"])
MODULES = {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "video_generation", "verbatim", "quality_report", "citation_report"}
MODULE_SCHEMAS = {
    "lesson_plan": LessonPlanContent,
    "ppt": PPTContent,
    "task_sheet": TaskSheetContent,
    "exercise": ExerciseContent,
    "video_script": SeedanceVideoScriptContent,
    "video_generation": SeedanceVideoGenerationContent,
    "verbatim": VerbatimContent,
    "quality_report": QualityReportContent,
    "citation_report": CitationReportContent,
}


def _lesson_plan_schema_for(content: dict) -> type:
    """V1/V2 按 schema_version 分派校验；V2 统一走 LessonPlanContentV2。"""
    from app.schemas.lesson_plan import LessonPlanContentV2

    return LessonPlanContentV2 if (content or {}).get("schema_version") == "2.0" else LessonPlanContent


def _video_script_schema_for(content: dict) -> type:
    """V3/V4 按 schema_version 分派校验；V4 统一走 SeedanceVideoScriptContentV4。"""
    from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, SeedanceVideoScriptContentV4

    return SeedanceVideoScriptContentV4 if (content or {}).get("schema_version") == VIDEO_SCRIPT_V4 else SeedanceVideoScriptContent


def _video_script_markdown(content: dict) -> str:
    """V4 按章节渲染 Markdown；V3 走通用渲染。"""
    from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, video_script_v4_to_markdown

    return video_script_v4_to_markdown(content) if (content or {}).get("schema_version") == VIDEO_SCRIPT_V4 else to_markdown("video_script", content)


def _lesson_plan_markdown(content: dict) -> str:
    """V2 从章节树渲染 Markdown；V1 走通用渲染。"""
    from app.schemas.lesson_plan import lesson_plan_to_markdown_v2

    return lesson_plan_to_markdown_v2(content)


def serialize(item: Artifact) -> dict:
    return {key: getattr(item, key) for key in ("id", "course_id", "artifact_type", "version", "blueprint_version", "content_json", "content_markdown", "status", "model_name", "prompt_version", "is_locked", "change_summary", "source_versions_json", "agent_profile_id", "created_at", "approved_at", "memory_revision_created")}


def _locked_value(content: dict, path: str):
    if path in {"", "$"}:
        return content
    value = content
    normalized = path.removeprefix("$.")
    parts = [part for part in re.split(r"\.|\[|\]", normalized) if part]
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list):
            if part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                matched = next(
                    (item for item in value if isinstance(item, dict) and item.get("id") == part),
                    None,
                )
                if matched is None:
                    return None
                value = matched
        else:
            return None
    return value


def _validate_locked_content(source: dict, revised: dict, locks: list[ArtifactLock]) -> None:
    for lock in locks:
        if _locked_value(source, lock.json_path) != _locked_value(revised, lock.json_path):
            raise HTTPException(409, f"模型修改了已锁定内容：{lock.json_path}")


def _validate_report_invariants(module_type: str, source: dict, revised: dict) -> None:
    if module_type == "quality_report":
        if revised.get("score") != source.get("score") or revised.get("issues") != source.get("issues"):
            raise HTTPException(422, "质量报告的规则得分和问题证据不能由模型修改")
    if module_type == "citation_report" and revised.get("source_refs") != source.get("source_refs"):
        raise HTTPException(422, "引用来源不能由模型新增、删除或替换")


async def _chat_session(course_id: str, module_type: str, db: AsyncSession) -> AgentChatSession | None:
    return await db.scalar(
        select(AgentChatSession).where(
            AgentChatSession.course_id == course_id,
            AgentChatSession.module_type == module_type,
        )
    )


@router.get("/courses/{course_id}/artifacts")
async def list_artifacts(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    items = await db.scalars(select(Artifact).where(Artifact.course_id == course_id).order_by(Artifact.artifact_type, Artifact.version.desc()))
    latest = {}
    for item in items:
        latest.setdefault(item.artifact_type, serialize(item))
    return list(latest.values())


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(Artifact, artifact_id)
    if not item:
        raise HTTPException(404, "资源不存在")
    await owned_course(item.course_id, user, db)
    return serialize(item)


@router.patch("/artifacts/{artifact_id}", status_code=201)
async def update_artifact(artifact_id: str, payload: ArtifactUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    source = await db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, "资源不存在")
    await owned_course(source.course_id, user, db)
    content_json = payload.content_json
    content_markdown = payload.content_markdown
    if source.artifact_type == "task_sheet":
        try:
            validated = TaskSheetContent.model_validate(payload.content_json)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        content_json = validated.model_dump()
        content_markdown = to_markdown("task_sheet", validated)
    elif source.artifact_type == "exercise":
        try:
            validated = ExerciseContent.model_validate(payload.content_json)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == source.course_id,
            CourseBlueprint.version == source.blueprint_version,
        ))
        if not blueprint:
            raise HTTPException(409, "课后练习对应的课程蓝图不存在")
        issues = validate_exercise(CourseBlueprintSchema.model_validate(blueprint.content_json), validated.model_dump())
        blocking = [item for item in issues if item["severity"] in {"critical", "major"}]
        if blocking:
            raise HTTPException(422, detail=blocking)
        asset_ids = {
            stimulus.visual.asset_id
            for section in validated.sections
            for block in section.blocks
            if getattr(block, "kind", "") == "question_group"
            for stimulus in block.stimuli
            if stimulus.visual and stimulus.visual.asset_id
        }
        for asset_id in asset_ids:
            asset = await db.scalar(select(ArtifactAsset).where(
                ArtifactAsset.id == asset_id,
                ArtifactAsset.course_id == source.course_id,
                ArtifactAsset.owner_id == user.id,
                ArtifactAsset.status == "approved",
            ))
            if not asset:
                raise HTTPException(422, f"配图资源 {asset_id} 不属于当前课程或尚未通过复核")
        content_json = validated.model_dump()
        content_markdown = to_markdown("exercise", validated)
    elif source.artifact_type == "video_script":
        try:
            schema = _video_script_schema_for(payload.content_json)
            validated = schema.model_validate(payload.content_json)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == source.course_id,
            CourseBlueprint.version == source.blueprint_version,
        ))
        if not blueprint:
            raise HTTPException(409, "视频脚本对应的课程蓝图不存在")
        source_versions = source.source_versions_json or {}
        lesson_query = select(Artifact).where(
            Artifact.course_id == source.course_id, Artifact.artifact_type == "lesson_plan",
        )
        if source_versions.get("lesson_plan"):
            lesson_query = lesson_query.where(Artifact.version == source_versions["lesson_plan"])
        else:
            lesson_query = lesson_query.order_by(Artifact.version.desc())
        lesson_artifact = await db.scalar(lesson_query)
        if not lesson_artifact:
            raise HTTPException(409, "视频脚本对应的教学设计版本不存在")
        issues = validate_video_script(
            CourseBlueprintSchema.model_validate(blueprint.content_json), validated.model_dump(),
            lesson_artifact.content_json, None,
        )
        blocking = [item for item in issues if item["severity"] in {"critical", "major"}]
        if blocking:
            raise HTTPException(422, detail=blocking)
        content_json = validated.model_dump()
        content_markdown = _video_script_markdown(content_json)
    elif source.artifact_type == "video_generation":
        try:
            schema = SeedanceVideoGenerationContent if payload.content_json.get("schema_version") == "3.0" else VideoGenerationContent
            validated_video = schema.model_validate(payload.content_json)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        referenced_assets = {
            asset_id
            for scene in validated_video.scenes
            for asset_id in (scene.video_asset_id, getattr(scene, "audio_asset_id", None), scene.thumbnail_asset_id)
            if asset_id
        } | {
            asset_id
            for asset_id in (
                validated_video.outputs.preview_asset_id,
                validated_video.outputs.final_asset_id,
                validated_video.outputs.subtitle_asset_id,
                validated_video.outputs.thumbnail_asset_id,
            )
            if asset_id
        }
        for asset_id in referenced_assets:
            asset = await db.scalar(select(ArtifactAsset).where(
                ArtifactAsset.id == asset_id,
                ArtifactAsset.course_id == source.course_id,
                ArtifactAsset.owner_id == user.id,
                ArtifactAsset.status == "approved",
            ))
            if not asset:
                raise HTTPException(422, f"视频资源 {asset_id} 不属于当前课程或尚未通过检查")
        content_json = validated_video.model_dump()
        content_markdown = (
            seedance_video_generation_markdown(validated_video)
            if isinstance(validated_video, SeedanceVideoGenerationContent)
            else video_generation_markdown(validated_video)
        )
    version = (await db.scalar(select(func.max(Artifact.version)).where(Artifact.course_id == source.course_id, Artifact.artifact_type == source.artifact_type)) or 0) + 1
    item = Artifact(course_id=source.course_id, artifact_type=source.artifact_type, version=version, blueprint_version=source.blueprint_version, content_json=content_json, content_markdown=content_markdown, status="draft", model_name=source.model_name, prompt_version=source.prompt_version, change_summary=payload.change_summary, source_versions_json=source.source_versions_json, agent_profile_id=source.agent_profile_id)
    db.add(item)
    await db.flush()
    await register_artifact_version(db, item)
    await db.commit()
    await db.refresh(item)
    return serialize(item)


@router.post("/artifacts/{artifact_id}/apply-template")
async def apply_ppt_template(
    artifact_id: str,
    payload: PPTTemplateApplyRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, "资源不存在")
    await owned_course(source.course_id, user, db)
    if source.artifact_type != "ppt":
        raise HTTPException(422, "只有 PPT 课件可以切换模板")
    template = get_ppt_template(payload.template_id)
    if not template:
        raise HTTPException(422, "PPT 模板不存在或已停用")
    if source.version != payload.expected_version:
        raise HTTPException(409, "当前 PPT 版本已变化，请刷新后重试")
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == source.course_id,
        CourseTask.task_type == "ppt",
    ))
    if task and task.current_artifact_id != source.id:
        raise HTTPException(409, "当前 PPT 已有新版本，请刷新后重试")
    if task and task.status in {"queued", "running"}:
        raise HTTPException(409, "PPT Agent 正在生成新版本，请完成后再切换模板")
    if source.is_locked:
        raise HTTPException(409, "当前 PPT 已锁定，无法切换模板")
    current_template = resolve_ppt_template((source.content_json or {}).get("theme"))
    if current_template["id"] == template["id"]:
        return {"artifact": serialize(source), "changed": False}

    content_json = json.loads(json.dumps(source.content_json or {}, ensure_ascii=False))
    content_json["theme"] = template["id"]
    version = (await db.scalar(select(func.max(Artifact.version)).where(
        Artifact.course_id == source.course_id,
        Artifact.artifact_type == "ppt",
    )) or 0) + 1
    item = Artifact(
        course_id=source.course_id,
        artifact_type="ppt",
        version=version,
        blueprint_version=source.blueprint_version,
        content_json=content_json,
        content_markdown=source.content_markdown,
        status="draft",
        model_name=source.model_name,
        prompt_version=source.prompt_version,
        change_summary=f"切换 PPT 模板：{template['name']}",
        source_versions_json=source.source_versions_json,
        agent_profile_id=source.agent_profile_id,
    )
    db.add(item)
    await db.flush()
    await register_artifact_version(db, item, invalidate_dependents=False)
    await db.commit()
    await db.refresh(item)
    return {"artifact": serialize(item), "changed": True}


@router.post("/artifacts/{artifact_id}/regenerate", status_code=201)
async def regenerate_artifact(artifact_id: str, payload: RegenerateRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    source = await db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, "资源不存在")
    await owned_course(source.course_id, user, db)
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == artifact_id)))
    if payload.path and any(lock.json_path == payload.path for lock in locks):
        raise HTTPException(409, "所选内容已锁定")
    version = (await db.scalar(select(func.max(Artifact.version)).where(Artifact.course_id == source.course_id, Artifact.artifact_type == source.artifact_type)) or 0) + 1
    content = dict(source.content_json)
    content["revision_note"] = {"path": payload.path or "all", "instruction": payload.instruction}
    item = Artifact(course_id=source.course_id, artifact_type=source.artifact_type, version=version, blueprint_version=source.blueprint_version, content_json=content, content_markdown=source.content_markdown + f"\n\n> 局部重生成指令：{payload.instruction}", model_name=source.model_name, prompt_version=source.prompt_version, change_summary=f"局部重生成：{payload.instruction[:80]}", agent_profile_id=source.agent_profile_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return serialize(item)


@router.post("/artifacts/{artifact_id}/lock")
async def lock_artifact(artifact_id: str, payload: LockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(Artifact, artifact_id)
    if not item:
        raise HTTPException(404, "资源不存在")
    await owned_course(item.course_id, user, db)
    db.add(ArtifactLock(artifact_id=item.id, json_path=payload.json_path, created_by=user.id))
    if payload.json_path in {"", "$"}:
        item.is_locked = True
    # 共享项目记忆：教师锁定决策进入项目记忆（同一事务，先写后 bump）。
    from app.services.project_knowledge_service import bump, index_decision

    await index_decision(
        db, item.course_id, f"decision-lock-{item.id}-{payload.json_path}",
        f"锁定 {item.artifact_type} V{item.version} 内容",
        f"教师锁定了 {item.artifact_type} V{item.version} 的路径 {payload.json_path}。",
        created_by="teacher",
        summary={"artifact_type": item.artifact_type, "artifact_version": item.version, "json_path": payload.json_path},
    )
    await bump(
        db, item.course_id, f"锁定 {item.artifact_type} 内容",
        source_type="decision", source_id=f"decision-lock-{item.id}-{payload.json_path}",
        created_by="teacher",
    )
    await db.commit()
    return {"locked": True, "path": payload.json_path}


@router.post("/artifacts/{artifact_id}/approve")
async def approve_artifact(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(Artifact, artifact_id)
    if not item:
        raise HTTPException(404, "资源不存在")
    await owned_course(item.course_id, user, db)
    item.status, item.approved_at = "approved", datetime.now(timezone.utc)
    await db.commit()
    return serialize(item)


@router.get("/artifacts/{artifact_id}/versions")
async def versions(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    source = await db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, "资源不存在")
    await owned_course(source.course_id, user, db)
    items = await db.scalars(select(Artifact).where(Artifact.course_id == source.course_id, Artifact.artifact_type == source.artifact_type).order_by(Artifact.version.desc()))
    return [serialize(x) for x in items]


@router.post("/artifacts/{artifact_id}/restore", status_code=201)
async def restore_artifact_version(
    artifact_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, "资源版本不存在")
    await owned_course(source.course_id, user, db)
    if source.artifact_type == "video_generation":
        if not is_publishable_video_artifact(source):
            raise HTTPException(409, "该历史版本不是可发布的原生有声视频，无法恢复")
        final_asset_id = ((source.content_json or {}).get("outputs") or {}).get("final_asset_id")
        final_asset = await db.scalar(select(ArtifactAsset).where(
            ArtifactAsset.id == final_asset_id,
            ArtifactAsset.course_id == source.course_id,
            ArtifactAsset.owner_id == user.id,
            ArtifactAsset.status == "approved",
        ))
        if not final_asset:
            raise HTTPException(409, "该历史视频的最终媒体资源已不可用，无法恢复")
    version = (await db.scalar(select(func.max(Artifact.version)).where(
        Artifact.course_id == source.course_id,
        Artifact.artifact_type == source.artifact_type,
    )) or 0) + 1
    restored = Artifact(
        course_id=source.course_id,
        artifact_type=source.artifact_type,
        version=version,
        blueprint_version=source.blueprint_version,
        content_json=json.loads(json.dumps(source.content_json, ensure_ascii=False)),
        content_markdown=source.content_markdown,
        status="draft",
        model_name=source.model_name,
        prompt_version=source.prompt_version,
        change_summary=f"恢复自 V{source.version}",
        source_versions_json=dict(source.source_versions_json or {}),
        agent_profile_id=source.agent_profile_id,
    )
    db.add(restored)
    await db.flush()
    await register_artifact_version(db, restored, invalidate_dependents=True)
    await db.commit()
    await db.refresh(restored)
    return serialize(restored)


@router.get("/courses/{course_id}/modules/{module_type}/chat/history")
async def chat_history(course_id: str, module_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    if module_type not in MODULES:
        raise HTTPException(404, "模块不存在")
    rows = await db.scalars(select(AgentMessage).where(
        AgentMessage.course_id == course_id,
        AgentMessage.module_type == module_type,
        # 模块对话（chat/send）无 run_id；带 run_id 的是 pipeline 对话单线（PPT 工作台上下文），
        # 不属于模块聊天，排除避免污染历史。
        AgentMessage.run_id.is_(None),
    ).order_by(AgentMessage.created_at))
    chat_session = await _chat_session(course_id, module_type, db)
    _, config = await resolve_provider(
        db,
        user.id,
        (chat_session.model_config_id if chat_session else None) or course.model_config_id,
    )
    return {
        "messages": [
            {"id": x.id, "role": x.role, "content": x.content, "artifact_id": x.artifact_id, "created_at": x.created_at}
            for x in rows
        ],
        "model_config_id": config.id if config else None,
    }


@router.patch("/courses/{course_id}/modules/{module_type}/chat/model")
async def update_chat_model(
    course_id: str,
    module_type: str,
    payload: AgentChatModelUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_course(course_id, user, db)
    if module_type not in MODULES:
        raise HTTPException(404, "模块不存在")
    config = await owned_model_config(db, user.id, payload.model_config_id)
    chat_session = await _chat_session(course_id, module_type, db)
    if chat_session:
        chat_session.model_config_id = config.id
    else:
        chat_session = AgentChatSession(
            course_id=course_id,
            module_type=module_type,
            model_config_id=config.id,
        )
        db.add(chat_session)
    await db.commit()
    return {"model_config_id": config.id}


@router.post("/courses/{course_id}/modules/{module_type}/chat/send", status_code=201)
async def chat_send(course_id: str, module_type: str, payload: RegenerateRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    if module_type not in MODULES:
        raise HTTPException(404, "模块不存在")
    source = await db.scalar(select(Artifact).where(Artifact.course_id == course_id, Artifact.artifact_type == module_type).order_by(Artifact.version.desc()))
    if not source:
        raise HTTPException(409, "模块尚未生成")
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
    if any(x.json_path in {"", "$"} for x in locks):
        raise HTTPException(409, "当前产物已整体锁定")
    if payload.path and any(x.json_path == payload.path for x in locks):
        raise HTTPException(409, "所选内容已锁定")
    chat_session = await _chat_session(course_id, module_type, db)
    preferred_id = (chat_session.model_config_id if chat_session else None) or course.model_config_id
    provider, config = await resolve_provider(db, user.id, preferred_id)
    if not chat_session:
        chat_session = AgentChatSession(
            course_id=course_id,
            module_type=module_type,
            model_config_id=config.id if config else None,
        )
        db.add(chat_session)

    version = source.version + 1
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == course_id, CourseTask.task_type == module_type,
    ))
    profile = await db.get(CourseTaskAgentProfile, task.current_agent_profile_id) if task and task.current_agent_profile_id else None
    if module_type in {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"} and (not profile or profile.status != "ready"):
        raise HTTPException(409, "项目专属 Agent 尚未初始化完成")
    if isinstance(provider, MockProvider):
        if module_type in {"task_sheet", "exercise"} and source.content_json.get("schema_version") != "2.0":
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == course_id,
                CourseBlueprint.version == source.blueprint_version,
            ))
            if not blueprint:
                raise HTTPException(409, "课程蓝图不存在，无法升级旧版产物")
            bp = CourseBlueprintSchema.model_validate(blueprint.content_json)
            content = (make_task_sheet(bp) if module_type == "task_sheet" else make_exercises(bp)).model_dump()
        else:
            content = dict(source.content_json)
        content["revision_note"] = {"path": payload.path or "all", "instruction": payload.instruction}
        revision = AgentArtifactRevision(
            content_json=content,
            content_markdown=source.content_markdown + f"\n\n> 教师修改指令：{payload.instruction}",
            assistant_reply=f"已根据指令创建 {module_type} 的 V{version}，原版本仍可在历史记录中恢复。",
        )
    else:
        schema = MODULE_SCHEMAS[module_type]
        if module_type == "lesson_plan":
            schema = _lesson_plan_schema_for(source.content_json)
        previous_messages = list(await db.scalars(
            select(AgentMessage).where(
                AgentMessage.course_id == course_id,
                AgentMessage.module_type == module_type,
            ).order_by(AgentMessage.created_at.desc()).limit(12)
        ))
        instruction = (
            "模块：" + module_type
            + "\n当前结构化内容：\n" + json.dumps(source.content_json, ensure_ascii=False)
            + "\n当前 Markdown：\n" + source.content_markdown
            + "\n最近对话：\n" + json.dumps(
                [{"role": item.role, "content": item.content} for item in reversed(previous_messages)],
                ensure_ascii=False,
            )
            + "\n锁定路径：\n" + json.dumps([item.json_path for item in locks], ensure_ascii=False)
            + "\n教师指令：\n" + payload.instruction
            + "\ncontent_json 必须符合：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        if profile:
            system, prompt = build_runtime_prompts(
                profile, AgentArtifactRevision.model_json_schema(), {}, instruction,
            )
        else:
            system = "你是课程质量与引用报告助手。不得修改规则证据，只返回符合输出 Schema 的 JSON。"
            prompt = instruction + "\n输出 Schema：\n" + json.dumps(AgentArtifactRevision.model_json_schema(), ensure_ascii=False)
        try:
            revision = await provider.structured(system, prompt, AgentArtifactRevision)
        except Exception as exc:
            raise HTTPException(502, f"模型修订失败，未创建新版本：{str(exc)[:240]}") from exc

    try:
        if module_type == "lesson_plan":
            validated_content = _lesson_plan_schema_for(revision.content_json).model_validate(revision.content_json).model_dump()
        else:
            validated_content = MODULE_SCHEMAS[module_type].model_validate(revision.content_json).model_dump()
    except ValidationError as exc:
        raise HTTPException(502, "模型返回内容不符合当前模块结构，未创建新版本") from exc
    _validate_locked_content(source.content_json, validated_content, locks)
    _validate_report_invariants(module_type, source.content_json, validated_content)
    if module_type == "lesson_plan" and validated_content.get("schema_version") == "2.0":
        rendered_markdown = _lesson_plan_markdown(validated_content)
    else:
        rendered_markdown = (
            to_markdown(module_type, MODULE_SCHEMAS[module_type].model_validate(validated_content))
            if module_type in {"task_sheet", "exercise"}
            else revision.content_markdown
        )
    user_message = AgentMessage(course_id=course_id, module_type=module_type, role="user", content=payload.instruction)
    db.add(user_message)
    artifact = Artifact(
        course_id=course_id,
        artifact_type=module_type,
        version=version,
        blueprint_version=source.blueprint_version,
        content_json=validated_content,
        content_markdown=rendered_markdown,
        model_name=resolved_model_name(provider, config),
        prompt_version=source.prompt_version,
        change_summary=f"Agent 对话修改：{payload.instruction[:80]}",
        agent_profile_id=profile.id if profile else source.agent_profile_id,
    )
    db.add(artifact)
    await db.flush()
    await register_artifact_version(db, artifact)
    reply = AgentMessage(
        course_id=course_id,
        module_type=module_type,
        role="assistant",
        content=revision.assistant_reply,
        artifact_id=artifact.id,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(artifact)
    return {"message": {"id": reply.id, "role": reply.role, "content": reply.content, "artifact_id": reply.artifact_id}, "artifact": serialize(artifact)}
