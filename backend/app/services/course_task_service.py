import asyncio
import json
import logging
import re
import time
from contextlib import suppress
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.agents.generators import (
    make_exercises,
    make_lesson_plan,
    make_ppt,
    make_task_sheet,
    make_verbatim,
    make_video_script,
    make_seedance_verbatim,
    make_seedance_video_script,
    repair_video_script_subtitles,
    to_markdown,
)
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.models.entities import (
    AgentMessage,
    AgentChatSession,
    Artifact,
    ArtifactAsset,
    ArtifactLock,
    CourseBlueprint,
    CourseProject,
    CourseRequirement,
    CourseTask,
    CourseTaskAgentProfile,
    GenerationEvent,
    GenerationRun,
    PipelineRun,
    QualityIssue,
    QualityReport,
)
from app.providers.llm.base import LLMProviderError
from app.providers.llm.mock import MockProvider
from app.schemas.artifact import (
    AgentArtifactRevisionPayload,
    ExerciseContent,
    LessonPlanContent,
    PPTContent,
    TaskSheetContent,
    VerbatimContent,
    VideoScriptContent,
    SeedanceVideoScriptContent,
)
from app.schemas.video import SeedanceVideoGenerationContent, VideoGenerationContent
from app.schemas.agent_profile import ExerciseProfile, LessonPlanProfile, TaskSheetProfile, VerbatimProfile, VideoScriptProfile
from app.schemas.blueprint import CourseBlueprintSchema, normalize_blueprint_references
from app.schemas.lesson_plan import LessonPlanContentV2, lesson_plan_to_markdown_v2
from app.schemas.task_sheet import TASK_SHEET_V3, TaskSheetContentV3, task_sheet_v3_to_markdown
from app.schemas.verbatim_v2 import VerbatimContentV2, verbatim_v2_to_markdown
from app.services.model_config_service import normalize_model_preferences, resolve_provider, resolved_model_name
from app.services.agent_prompt_service import (
    active_prompt_template,
    apply_output_rules,
    build_runtime_prompts,
    ensure_prompt_templates,
    prepare_profile_prompts,
)
from app.services.project_knowledge_service import build_project_knowledge_context
from app.services.exercise_review_service import degrade_unreviewed_visuals, review_and_repair_exercise
from app.services.exercise_visual_service import process_exercise_visuals
from app.services.quality_service import validate_exercise, validate_resources, validate_video_script
from app.services.video_generation_settings_service import (
    VideoGenerationSettingsPatch,
    apply_video_generation_settings,
    preferred_video_resolution,
)
from app.agent.agents.lesson_plan.qa import validate_lesson_plan
from app.agent.core.error import AgentError
from app.services.ppt_template_service import DEFAULT_PPT_TEMPLATE_ID, resolve_ppt_template
from app.agent.pipeline import PipelinePaused  # noqa: E402

logger = logging.getLogger(__name__)


class TaskValidationError(RuntimeError):
    """A safe, actionable artifact validation failure that may be shown to users."""


def _task_failure_payload(exc: Exception) -> tuple[dict, str]:
    """Normalize stable runtime failures without erasing domain AgentError codes."""
    from app.agent.schemas import PPTAgentError

    runtime_errors = (LLMProviderError, PPTAgentError, AgentError)
    code = (
        exc.code
        if isinstance(exc, runtime_errors)
        else "task_validation_failed"
        if isinstance(exc, TaskValidationError)
        else "task_generation_failed"
    )
    internal_detail = str(exc).strip()[:500]
    safe_runtime_prefixes = (
        "流水线", "页面内容 Agent", "LLM 布局", "PPT 编辑", "布局结果", "Agent ",
    )
    message = (
        exc.user_message
        if isinstance(exc, runtime_errors)
        else internal_detail
        if isinstance(exc, TaskValidationError)
        else internal_detail
        if isinstance(exc, RuntimeError) and internal_detail.startswith(safe_runtime_prefixes)
        else "任务生成暂时失败，请重试或切换模型。"
    )
    retryable = exc.retryable if isinstance(exc, runtime_errors) else True
    error = {"code": code, "message": message, "retryable": retryable}
    if isinstance(exc, (PPTAgentError, AgentError)) and exc.details:
        error["details"] = exc.details
    return error, internal_detail


TASK_SPECS = (
    ("lesson_plan", "教学设计", "教学设计 Agent", "lesson_plan_agent", []),
    # 共享项目记忆架构：内容 Agent 之间不再有调度依赖，全部并行启动。
    # 历史可选引用记录在 OPTIONAL_REFERENCE_TYPES 中，仅影响上下文快照，不阻塞启动。
    ("ppt", "PPT 课件", "PPT Agent", "ppt_agent", []),
    ("task_sheet", "学习任务单", "任务单 Agent", "task_sheet_agent", []),
    ("exercise", "课后练习", "练习 Agent", "exercise_agent", []),
    ("video_script", "视频脚本", "视频脚本 Agent", "video_script_agent", []),
    ("video_generation", "视频生成", "视频生成工作流", "video_generation_pipeline", ["video_script"]),
    ("verbatim", "教师逐字稿", "逐字稿 Agent", "verbatim_agent", []),
)
TASK_SPEC_BY_TYPE = {item[0]: item for item in TASK_SPECS}
CONTENT_TASK_TYPES = {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"}

#: 每个 Agent 在共享项目记忆中可读取的可选参考来源（不控制启动顺序）。
OPTIONAL_REFERENCE_TYPES = {
    "lesson_plan": ["task_sheet", "ppt", "exercise", "video_script", "verbatim"],
    "ppt": ["lesson_plan", "task_sheet", "video_script", "verbatim", "exercise"],
    "task_sheet": ["lesson_plan", "ppt", "exercise", "video_script", "verbatim"],
    "exercise": ["lesson_plan", "task_sheet", "ppt", "video_script", "verbatim"],
    "video_script": ["lesson_plan"],
    "verbatim": ["video_script", "ppt"],
}

#: 运行输入契约：执行时必须满足的事实条件（video_generation 属于运行输入契约，
#: 不是 Agent 拓扑依赖——缺少脚本只影响视频生成本身，不阻塞其他 Agent）。
VIDEO_INPUT_CONTRACT = {"video_script": "执行前必须存在最新且有效的 Seedance V3/V4 视频脚本"}
TASK_SCHEMAS = {
    "lesson_plan": LessonPlanContent,
    "ppt": PPTContent,
    "task_sheet": TaskSheetContent,
    "exercise": ExerciseContent,
    "video_script": SeedanceVideoScriptContent,
    "video_generation": SeedanceVideoGenerationContent,
    "verbatim": VerbatimContentV2,
}

task_jobs: dict[str, asyncio.Task] = {}
schedule_locks: dict[str, asyncio.Lock] = {}
initial_generation_semaphores: dict[str, asyncio.Semaphore] = {}
GENERATION_HEARTBEAT_SECONDS = 2.0

PHASE_LABELS = {
    "preparing": "读取项目专属配置",
    "analyzing": "理解任务要求与影响范围",
    "generating": "生成结构化新版本",
    "validating": "校验结构与锁定内容",
    "replying": "组织 Agent 回复",
    "saving": "保存新版本并更新依赖",
    "completed": "新版本生成完成",
}

PHASE_DETAILS = {
    "preparing": "正在加载当前任务的专属配置、课程蓝图和共享项目记忆快照。",
    "analyzing": "正在识别需要调整的内容范围，并确认必须保留的约束。",
    "generating": "正在依据项目专属配置生成结构化任务文件。",
    "validating": "正在检查输出结构、锁定内容、引用和版本一致性。",
    "replying": "文件内容已通过校验，正在生成简洁的修改说明。",
    "saving": "正在原子保存文件、对话消息并更新项目记忆。",
    "completed": "新版本已保存，旧版本仍可在版本历史中查看。",
}


def utcnow():
    return datetime.now(timezone.utc)


def artifact_payload(item: Artifact | None) -> dict | None:
    if not item:
        return None
    payload = {
        key: getattr(item, key)
        for key in (
            "id", "course_id", "artifact_type", "version", "blueprint_version",
            "content_json", "content_markdown", "status", "model_name", "prompt_version",
            "is_locked", "change_summary", "source_versions_json", "created_at", "approved_at",
            "agent_profile_id", "memory_revision_created",
        )
    }
    for key in ("created_at", "approved_at"):
        if payload[key] is not None:
            payload[key] = payload[key].isoformat()
    return payload


def is_publishable_video_artifact(item: Artifact | None) -> bool:
    """Return true when a native artifact has a final video or a playable clip.

    A cancelled multi-scene run may still contain successfully generated scenes.
    Those clips are valid reviewable outputs and must not be hidden merely because
    the full timeline was not composed.
    """
    if not item or item.artifact_type != "video_generation":
        return False
    content = item.content_json or {}
    outputs = content.get("outputs") or {}
    scenes = content.get("scenes") or []
    has_ready_clip = any(
        isinstance(scene, dict)
        and scene.get("status") == "ready"
        and scene.get("video_asset_id")
        for scene in scenes
    )
    return bool(
        content.get("schema_version") == "3.0"
        and content.get("mode") == "seedance_native"
        and (outputs.get("final_asset_id") or has_ready_clip)
    )


async def video_script_generation_readiness(
    db, course_id: str,
) -> tuple[Artifact | None, dict | None]:
    """Resolve the latest script and an actionable waiting reason.

    Approval is deliberately not part of this check: script approval remains a
    delivery marker, while video generation always consumes the newest valid draft.
    """
    script = await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id,
        Artifact.artifact_type == "video_script",
    ).order_by(Artifact.version.desc()))
    if not script:
        return None, {
            "code": "video_script_missing",
            "message": "请先生成视频脚本；脚本生成完成后即可选择视频模型并获取报价。",
            "retryable": True,
        }
    try:
        from app.schemas.video_script_v4 import seedance_video_script_for_generation

        seedance_video_script_for_generation(script.content_json or {})
    except (TypeError, ValueError):
        return None, {
            "code": "video_script_invalid",
            "message": "最新视频脚本结构过旧或无效，请先同步或升级视频脚本。",
            "retryable": True,
        }
    return script, None


async def task_payload(db, item: CourseTask, *, event_cursor: int | None = None) -> dict:
    artifact = await db.get(Artifact, item.current_artifact_id) if item.current_artifact_id else None
    profile = await db.get(CourseTaskAgentProfile, item.current_agent_profile_id) if item.current_agent_profile_id else None
    spec = TASK_SPEC_BY_TYPE[item.task_type]
    stale_dependencies = []
    activities = []
    current_activity = None
    if item.active_run_id:
        activity_events = list(await db.scalars(
            select(GenerationEvent).where(
                GenerationEvent.run_id == item.active_run_id,
                GenerationEvent.event_type == "task_activity_updated",
            ).order_by(GenerationEvent.id)
        ))
        activities_by_phase = {}
        for event in activity_events:
            data = event.data_json or {}
            phase = data.get("phase")
            if not phase:
                continue
            activity = {
                "phase": phase,
                "label": data.get("phase_label") or phase,
                "detail": data.get("detail") or "",
                "status": data.get("phase_status") or "running",
                "progress": data.get("progress", item.progress),
                "elapsed_ms": data.get("elapsed_ms") or 0,
            }
            activities_by_phase[phase] = activity
            current_activity = activity
        activities = list(activities_by_phase.values())
    if artifact:
        for dependency in item.dependency_types_json:
            latest_version = await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == item.course_id,
                Artifact.artifact_type == dependency,
            ))
            if latest_version and (artifact.source_versions_json or {}).get(dependency) != latest_version:
                stale_dependencies.append(dependency)
    # 共享项目记忆：当前可读取的参考产物 + 缺失的可选来源（仅提示，不阻塞）。
    available_sources: dict[str, dict] = {}
    missing_optional_sources: list[str] = []
    if item.task_type in CONTENT_TASK_TYPES:
        sibling_types = OPTIONAL_REFERENCE_TYPES.get(item.task_type, [])
        for reference_type in sibling_types:
            sibling_task = await db.scalar(select(CourseTask).where(
                CourseTask.course_id == item.course_id,
                CourseTask.task_type == reference_type,
            ))
            sibling_artifact = (
                await db.get(Artifact, sibling_task.current_artifact_id)
                if sibling_task and sibling_task.current_artifact_id
                else None
            )
            if sibling_artifact:
                available_sources[reference_type] = {
                    "version": sibling_artifact.version,
                    "status": sibling_artifact.status,
                }
            else:
                missing_optional_sources.append(reference_type)
    payload = {
        "id": item.id,
        "course_id": item.course_id,
        "task_type": item.task_type,
        "display_name": spec[1],
        "agent_name": spec[2],
        "agent_type": item.agent_type,
        "display_order": item.display_order,
        "status": item.status,
        "progress": item.progress,
        "dependency_types": item.dependency_types_json,
        "stale_dependencies": stale_dependencies,
        "optional_reference_types": item.optional_reference_types_json,
        "required_input_contract": item.required_input_contract_json,
        "memory_revision": item.last_context_revision,
        "last_context_revision": item.last_context_revision,
        "available_sources": available_sources,
        "missing_optional_sources": missing_optional_sources,
        "agent_profile_status": item.agent_profile_status,
        "agent_profile_version": profile.version if profile else 0,
        "agent_profile_template_version": profile.template_version if profile else None,
        "agent_profile_summary": profile.summary_json if profile else None,
        "stale_agent_profile": bool(artifact and profile and artifact.agent_profile_id != profile.id),
        "agent_profile_error": item.agent_profile_error_json,
        "current_artifact": artifact_payload(artifact),
        "active_run_id": item.active_run_id,
        "activity_run_id": item.active_run_id,
        "activities": activities,
        "current_activity": current_activity,
        "error": item.error_json,
        "updated_at": item.updated_at,
        "preferred_video_resolution": await _preferred_video_resolution(db, item),
        "video_generation_capabilities": await _video_generation_capabilities(db, item),
    }
    if event_cursor is not None:
        payload["event_cursor"] = event_cursor
    return payload


async def _video_generation_capabilities(db, item: CourseTask) -> dict | None:
    if item.task_type not in {"video_generation", "video_script"}:
        return None
    try:
        from app.services.video_generation_capability_service import get_video_generation_capabilities
        course = await db.get(CourseProject, item.course_id)
        return (await get_video_generation_capabilities(db, course)).payload() if course else None
    except (ValueError, RuntimeError) as exc:
        return {
            "provider": "unknown",
            "model_name": "unknown",
            "api_mode": "",
            "supported_resolutions": [],
            "duration_seconds": [0, 0],
            "source": "preflight_error",
            "available": False,
            "error_code": "video_capability_preflight_failed",
            "unavailable_reason": str(exc),
            "missing_dependencies": [],
            "audio_transcription_source": None,
            "audio_transcription_model": None,
        }


async def _preferred_video_resolution(db, item: CourseTask) -> str | None:
    """返回课程级视频生成分辨率偏好（由视频脚本 Agent 保存）。"""
    if item.task_type not in ("video_generation", "video_script"):
        return None
    course = await db.get(CourseProject, item.course_id)
    if not course:
        return None
    return preferred_video_resolution(course)


async def ensure_course_tasks(db, course_id: str) -> list[CourseTask]:
    existing = list(await db.scalars(
        select(CourseTask).where(CourseTask.course_id == course_id).order_by(CourseTask.display_order)
    ))
    by_type = {item.task_type: item for item in existing}
    for order, (task_type, _, _, agent_type, dependencies) in enumerate(TASK_SPECS, 1):
        if task_type in by_type:
            current = by_type[task_type]
            if current.display_order != order:
                current.display_order = order
            if current.agent_type != agent_type:
                current.agent_type = agent_type
            if current.dependency_types_json != dependencies:
                current.dependency_types_json = dependencies
            optional_refs = OPTIONAL_REFERENCE_TYPES.get(task_type, [])
            if current.optional_reference_types_json != optional_refs:
                current.optional_reference_types_json = optional_refs
            if task_type == "video_generation" and current.required_input_contract_json != VIDEO_INPUT_CONTRACT:
                current.required_input_contract_json = VIDEO_INPUT_CONTRACT
            if task_type == "video_generation":
                current.agent_profile_status = "ready"
                current_artifact = await db.get(Artifact, current.current_artifact_id) if current.current_artifact_id else None
                if current_artifact and not is_publishable_video_artifact(current_artifact):
                    # Keep legacy text/hybrid artifacts in version history, but
                    # never expose them as the official stage-06 task file.
                    current.current_artifact_id = None
                    current.status = "waiting_dependency"
                    current.progress = 0
                    current.completed_at = None
                    current.error_json = None
            continue
        artifact = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id,
            Artifact.artifact_type == task_type,
        ).order_by(Artifact.version.desc()))
        if task_type == "video_generation" and not is_publishable_video_artifact(artifact):
            artifact = None
        status = "approved" if artifact and artifact.status == "approved" else "review" if artifact else "waiting_dependency"
        task = CourseTask(
            course_id=course_id,
            task_type=task_type,
            agent_type=agent_type,
            display_order=order,
            status=status,
            progress=100 if artifact else 0,
            dependency_types_json=dependencies,
            optional_reference_types_json=OPTIONAL_REFERENCE_TYPES.get(task_type, []),
            required_input_contract_json=VIDEO_INPUT_CONTRACT if task_type == "video_generation" else {},
            current_artifact_id=artifact.id if artifact else None,
            completed_at=artifact.created_at if artifact else None,
            agent_profile_status="ready" if task_type == "video_generation" else "pending",
        )
        db.add(task)
        by_type[task_type] = task
    await db.flush()

    # 视频生成没有首稿 Artifact，不能靠 source_versions_json 判断上游是否仍然可用。
    # 旧逻辑只检查“是否存在过”视频脚本和 PPT，因此旧版 V1 脚本或已经 stale 的
    # 脚本也会把按钮错误地标成“可生成”，直到 Pydantic 在启动时抛出内部校验错误。
    video_task = by_type.get("video_generation")
    if (
        video_task
        and not video_task.current_artifact_id
        and not video_task.active_run_id
        and video_task.status in {"waiting_dependency", "ready_to_generate"}
    ):
        script_ready, waiting_reason = await video_script_generation_readiness(db, course_id)
        video_task.status = "ready_to_generate" if script_ready else "waiting_dependency"
        video_task.progress = 0
        video_task.error_json = waiting_reason
    return sorted(by_type.values(), key=lambda item: item.display_order)


async def _latest_artifact(db, course_id: str, task_type: str) -> Artifact | None:
    return await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id,
        Artifact.artifact_type == task_type,
    ).order_by(Artifact.version.desc()))


async def _emit(db, run: GenerationRun, event_type: str, task: CourseTask | None = None, **data):
    payload = {
        "course_id": run.course_id,
        "run_id": run.id,
        "task_id": task.id if task else None,
        "task_type": task.task_type if task else None,
        **data,
    }
    db.add(GenerationEvent(run_id=run.id, event_type=event_type, data_json=payload))


async def _publish_task_event(
    run_id: str,
    event_type: str,
    *,
    progress: int | None = None,
    **data,
):
    """Publish an event in a short transaction so SSE can observe it immediately."""
    # Heartbeat/SSE telemetry is best-effort.  During initial generation the
    # six task writers and the main task transaction can briefly contend for
    # SQLite's single writer.  Retrying this short transaction prevents a
    # telemetry write from turning a successfully generated artifact into a
    # failed task.
    for attempt in range(4):
        try:
            async with SessionLocal() as db:
                run = await db.get(GenerationRun, run_id)
                task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
                if not run or not task:
                    return
                if progress is not None and run.status not in {"completed", "failed", "cancelled"}:
                    run.progress = progress
                    task.progress = progress
                await _emit(
                    db,
                    run,
                    event_type,
                    task,
                    status=task.status,
                    progress=progress if progress is not None else task.progress,
                    **data,
                )
                await db.commit()
            return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == 3:
                logger.warning(
                    "Skipped task event after SQLite remained locked",
                    extra={"run_id": run_id, "event_type": event_type},
                )
                return
            await asyncio.sleep(0.05 * (2 ** attempt))


async def _publish_activity(
    run_id: str,
    phase: str,
    progress: int,
    phase_status: str = "running",
    *,
    elapsed_ms: int = 0,
    detail: str | None = None,
):
    await _publish_task_event(
        run_id,
        "task_activity_updated",
        progress=progress,
        phase=phase,
        phase_label=PHASE_LABELS[phase],
        detail=detail or PHASE_DETAILS[phase],
        phase_status=phase_status,
        elapsed_ms=elapsed_ms,
    )


async def _generation_heartbeat(run_id: str, started_at: float):
    progress = 30
    try:
        while True:
            await _publish_activity(
                run_id,
                "generating",
                progress,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            await asyncio.sleep(GENERATION_HEARTBEAT_SECONDS)
            # Keep visibly moving during providers with a long time-to-first-token.
            progress = min(72, progress + 1)
    except asyncio.CancelledError:
        raise


async def _run_with_generation_heartbeat(run_id: str, awaitable):
    started_at = time.monotonic()
    heartbeat = asyncio.create_task(_generation_heartbeat(run_id, started_at))
    try:
        return await awaitable, int((time.monotonic() - started_at) * 1000)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def create_task_run(db, task: CourseTask, trigger_type: str, user_message: AgentMessage | None = None) -> GenerationRun:
    await _ensure_current_task_profile(db, task)
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前任务已有 Agent 正在运行")
    if task.agent_profile_status != "ready" or not task.current_agent_profile_id:
        raise ValueError("项目专属 Agent 尚未初始化完成")
    run = GenerationRun(
        course_id=task.course_id,
        course_task_id=task.id,
        thread_id=str(uuid4()),
        run_type="task",
        trigger_type=trigger_type,
        status="queued",
        current_node=task.agent_type,
        agent_profile_id=task.current_agent_profile_id,
    )
    db.add(run)
    await db.flush()
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    if user_message:
        user_message.task_id = task.id
        user_message.run_id = run.id
        user_message.status = "pending"
    await _emit(db, run, "task_status_changed", task, status="queued", progress=0)
    return run


async def _execute_dispatched_task_run(run_id: str):
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
        task_type = task.task_type if task else ""
        course_id = run.course_id if run else ""
        trigger_type = run.trigger_type if run else ""
    if task_type == "video_generation":
        from app.services.seedance_video_generation_service import execute_seedance_video_run
        await execute_seedance_video_run(run_id)
        return
    if trigger_type == "initial" and course_id:
        limit = max(1, get_settings().initial_generation_concurrency)
        semaphore = initial_generation_semaphores.setdefault(course_id, asyncio.Semaphore(limit))
        async with semaphore:
            await execute_task_run(run_id)
        return
    await execute_task_run(run_id)


def start_task_run(run_id: str):
    job = asyncio.create_task(_execute_dispatched_task_run(run_id))
    task_jobs[run_id] = job


async def schedule_ready_tasks(course_id: str):
    lock = schedule_locks.setdefault(course_id, asyncio.Lock())
    async with lock:
        await _schedule_ready_tasks(course_id)


async def _schedule_ready_tasks(course_id: str):
    run_ids: list[str] = []
    batch_id = ""
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        if not course:
            return
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        if not blueprint or blueprint.status != "approved":
            return
        items = await ensure_course_tasks(db, course_id)
        tasks_by_type = {item.task_type: item for item in items}
        # 共享项目记忆架构：内容 Agent 之间没有调度依赖。只要 Agent 初始化就绪、
        # 没有正在运行的任务且还没有首稿 Artifact，就直接进入队列并行启动；
        # 视频生成仍按运行输入契约（存在 V3/V4 脚本）决定是否可生成。
        pending_content = [
            item for item in items
            if item.task_type in CONTENT_TASK_TYPES
            and item.status == "waiting_dependency"
            and not item.active_run_id
            and not item.current_artifact_id
            and item.agent_profile_status == "ready"
            and item.current_agent_profile_id
        ]
        video_task = tasks_by_type.get("video_generation")
        if pending_content:
            batch_id = str(uuid4())[:8]
        for item in pending_content:
            run = await create_task_run(db, item, "initial")
            run.batch_id = batch_id
            run_ids.append(run.id)
        if video_task and not video_task.current_artifact_id and not video_task.active_run_id and video_task.status in {"waiting_dependency", "ready_to_generate"}:
            script_ready, waiting_reason = await video_script_generation_readiness(db, course_id)
            video_task.status = "ready_to_generate" if script_ready else "waiting_dependency"
            video_task.progress = 0
            video_task.error_json = waiting_reason
        if run_ids:
            course.status = "resource_generating"
        await db.commit()
    for run_id in run_ids:
        start_task_run(run_id)


async def _profile_provider(db, course: CourseProject, task: CourseTask):
    profile = await db.get(CourseTaskAgentProfile, task.current_agent_profile_id) if task.current_agent_profile_id else None
    if not profile or profile.status != "ready":
        raise RuntimeError("项目专属 Agent 配置尚未准备完成")
    chat_session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == task.task_type,
    ))
    provider, config = await resolve_provider(
        db, course.owner_id,
        (chat_session.model_config_id if chat_session else None) or course.model_config_id,
    )
    return profile, provider, config


async def _ensure_current_task_profile(db, task: CourseTask) -> CourseTaskAgentProfile | None:
    profile = await db.get(CourseTaskAgentProfile, task.current_agent_profile_id) if task.current_agent_profile_id else None
    if task.task_type not in {"task_sheet", "exercise", "video_script", "lesson_plan", "verbatim"} or not profile or profile.status != "ready":
        return profile
    await ensure_prompt_templates(db)
    template = await active_prompt_template(db, task.agent_type)
    if profile.prompt_template_id == template.id:
        return profile
    course = await db.get(CourseProject, task.course_id)
    blueprint = await db.scalar(select(CourseBlueprint).where(
        CourseBlueprint.course_id == task.course_id,
        CourseBlueprint.version == profile.blueprint_version,
    ))
    if not course or not blueprint:
        raise RuntimeError("Agent V2 升级时缺少课程或蓝图上下文")
    context = dict(profile.context_json or {})
    upgrades = ({
        "objective_evidence_alignment_requirements": ["每项任务关联课程目标、知识点与可验收的学习证据"],
        "lesson_plan_reference_requirements": ["教学设计存在时软引用其环节与学习证据，不存在时不阻塞生成"],
        "recording_space_requirements": ["至少提供一个可填写的观察或记录表"],
        "student_language_requirements": ["使用学生能直接执行的动作语言"],
        "exercise_boundary_requirements": ["不生成完整题库、参考答案或教师解析"],
    } if task.task_type == "task_sheet" else {
        "objective_evidence_alignment_requirements": ["每道计分题关联目标、知识点、教学环节和可判定学习证据"],
        "lesson_plan_reference_requirements": ["教学设计存在时优先参考阶段、活动、评价证据与误区；不存在时不阻塞生成"],
        "task_sheet_non_reuse_requirements": ["借鉴目标、情境和支架，但不得直接复用任务步骤或过程性问题"],
        "section_and_scoring_requirements": ["三区均非空，总分固定为 100 分，题目和评分点分值守恒"],
        "printable_answer_space_requirements": ["学生版隐藏答案并为每题提供匹配的作答空间"],
        "visual_stimulus_requirements": ["最多三张必要配图，精确图示使用确定性图形，视觉材料必须提供替代材料"],
        "review_and_repair_requirements": ["检查答案、干扰项、可解性和评分点；自动修复最多一次"],
    } if task.task_type == "exercise" else {
        "objective_alignment_requirements": ["每个分镜映射真实的课程目标、知识点与教学环节"],
        "narrative_arc_requirements": ["章节目录是动态的：由 AI 根据课程内容与教师意图决定章节数量、标题、顺序与分镜归属，不固定为导入—建构—示范—检查—总结"],
        "segmentation_requirements": ["一个教学动作、一个主要场景和一个完整口播单元组成 4–15 秒片段，且每段必须且只能属于一个章节"],
        "continuity_requirements": ["同一人物和环境使用稳定连续性分组"],
        "visual_prompt_requirements": ["明确主体、环境、动作、镜头和视觉风格，不引用 PPT"],
        "native_audio_requirements": ["口播与声音指导交由 Seedance 原生音轨生成，不设计 TTS"],
        "fact_qa_requirements": ["列出必需术语、数字、单位和不可改变的教学结论"],
        "negative_constraint_requirements": ["禁止字幕、水印、乱码、幻灯片、界面和错误公式"],
        "timing_and_pacing_requirements": ["不截断句子，过长拆分，过短同场景合并；同章分镜在时间轴上连续，总时长守恒"],
        "cost_control_requirements": ["默认 720p 单候选，保持片段独立可复用"],
        "verbatim_handoff_requirements": ["按 scene_id 交付稳定口播和时间轴"],
        "review_and_repair_requirements": ["检查引用、时长、事实基准与原生生成可执行性；新章节/分镜 ID 由系统生成，禁止编造或批量改号"],
    } if task.task_type == "video_script" else {
        "scene_alignment_requirements": ["逐字稿每段对齐视频脚本场景（scene_id），时间轴为权威数值"],
        "fact_preservation_requirements": ["改写口播必须保留源场景的必需术语/数字/教学结论"],
        "speaking_style_requirements": ["必讲承载事实与结论，补充仅作时间允许时的举例；语气/重音/互动与该段教学动作匹配"],
        "timing_requirements": ["口播字数按语速换算后不得超过段落时长，停顿用于时间轴适配"],
        "deterministic_metrics_requirements": ["word_count 与 estimated_duration_seconds 由系统确定性计算，禁止伪造"],
    } if task.task_type == "verbatim" else {
        "alignment_requirements": ["每个目标必须对应教学活动和学习证据"],
        "timeline_requirements": ["各环节时长之和等于课程总时长"],
        "board_and_homework_requirements": ["板书突出核心关系", "作业直接覆盖课程目标"],
    })
    for key, value in upgrades.items():
        context.setdefault(key, value)
    specialized = {
        "task_sheet": TaskSheetProfile,
        "exercise": ExerciseProfile,
        "video_script": VideoScriptProfile,
        "lesson_plan": LessonPlanProfile,
        "verbatim": VerbatimProfile,
    }[task.task_type].model_validate(context)
    system_prompt, task_prompt, digest = prepare_profile_prompts(
        template, specialized.model_dump(), course, blueprint.content_json, blueprint.version,
    )
    version = (await db.scalar(select(func.max(CourseTaskAgentProfile.version)).where(
        CourseTaskAgentProfile.course_task_id == task.id,
    )) or 0) + 1
    profile.status = "superseded"
    upgraded = CourseTaskAgentProfile(
        course_id=profile.course_id,
        course_task_id=profile.course_task_id,
        task_type=profile.task_type,
        agent_type=profile.agent_type,
        version=version,
        initialization_run_id=profile.initialization_run_id,
        prompt_template_id=template.id,
        template_version=template.version,
        requirement_version=profile.requirement_version,
        blueprint_version=profile.blueprint_version,
        context_json=specialized.model_dump(),
        summary_json=specialized.summary(course.audience).model_dump(),
        rendered_system_prompt=system_prompt,
        rendered_task_template=task_prompt,
        prompt_hash=digest,
        model_name=profile.model_name,
        status="ready",
    )
    db.add(upgraded)
    await db.flush()
    task.current_agent_profile_id = upgraded.id
    task.agent_profile_status = "ready"
    return upgraded


def _ppt_template_instruction(theme_id: str | None) -> str:
    """把所选主题模板与 15 页结构注入 PPT 生成指令，让 AI 按模板生成内容。"""
    return (
        f"\n当前主题模板：{theme_id or DEFAULT_PPT_TEMPLATE_ID}。"
        "请严格按该模板的 15 页结构生成 slides"
        "（见 ppt_design_knowledge.ppt_skills.template_designs 中该模板的 page_structure 与版式说明），"
        "顺序固定为 cover/intro/objectives/knowledge_map/knowledge_intro/core_1/core_2/core_3/core_4/"
        "case_study/discussion/summary/assessment/assignment/end；"
        "每页 body 与该模板对应版式的槽位语义一致，页数保持 15 页。"
    )


_PPT_REVISION_QUALITY = (
    "\n请先分析用户意图与当前 PPT 结构，然后输出【完整的修订后 PPT】content_json。质量要求：\n"
    "· 只修改用户要求的部分，未受影响的页面/字段必须原样保留；\n"
    "· 遵守 ppt_design_knowledge 的 density_limits（标题≤30字、每条正文≤25字、每页≤6条、备注≥30字）；\n"
    "· 保持所选模板的 15 页结构与版式；标题用结论式措辞，不用“学习目标/核心概念”等主题式标题；\n"
    "· 若用户要求生成/插入图片：由于当前不支持二进制图片文件生成，请将插图需求转为视觉占位块（在 Slide 的 blocks 数组中增加 kind=\"visual\" 的 PPTVisualBlock 元素，填写 caption 或 diagram 等属性），或在 visual_suggestion 中提供图片视觉与排版说明，严禁输出非 Schema 字段；\n"
    "· 不要为了优化而增加页数或堆砌文字，保持信息密度与克制；\n"
    "· content_json 必须完整且符合 Schema。"
)

_PPT_REVISION_MAX_ROUNDS = 2


def _ppt_revision_prompt(base: str, content: dict, attempt: int, feedback: str = "") -> str:
    text = (
        base
        + "\n当前结构化内容：\n" + json.dumps(content, ensure_ascii=False)
        + _PPT_REVISION_QUALITY
    )
    if attempt > 1 and feedback:
        text += "\n上次校验未通过，请修正后重新输出完整修订稿：\n" + feedback[:1500]
    return text


def _clip_item(text: str, limit: int = 25) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit]


def _restore_locked_paths(content: dict, original: dict, locks) -> dict:
    """把 AI 改动过的锁定路径还原为原值，保证不触碰锁定内容。"""
    for lock in locks or []:
        path = getattr(lock, "json_path", None)
        if isinstance(lock, dict):
            path = lock.get("json_path")
        if not path or path in {"", "$"}:
            continue
        old = _locked_value(original, path)
        if _locked_value(content, path) != old:
            _set_locked_value(content, path, old)
    return content


def _set_locked_value(content, path: str, value):
    parts = [p for p in re.split(r"\.|\[|\]", path.removeprefix("$.")) if p]
    if not parts:
        return
    node = content
    for part in parts[:-1]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, list):
            node = next((entry for entry in node if isinstance(entry, dict) and entry.get("id") == part), None)
            if node is None:
                return
        else:
            return
    last = parts[-1]
    if isinstance(node, dict):
        node[last] = value
    elif isinstance(node, list) and last.isdigit() and int(last) < len(node):
        node[int(last)] = value
    elif isinstance(node, list):
        target = next((entry for entry in node if isinstance(entry, dict) and entry.get("id") == last), None)
        if target is not None:
            node[node.index(target)] = value


_VALID_PPT_BLOCK_KINDS = {"lead", "bullets", "steps", "compare", "quote", "visual", "note"}


def _coerce_unknown_blocks(slides: list[dict]) -> int:
    """把模型新发明的非法内容块（如 kind='cards'）规范化为合法的 bullets。

    返回被修正/丢弃的块数量。这样非法结构不会在流水线末端 PPTContent
    校验时硬失败，内容也能以合法结构保留下来。
    """
    fixed = 0
    for slide in slides:
        blocks = slide.get("blocks") or []
        if not blocks:
            continue
        coerced: list[dict] = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("kind") in _VALID_PPT_BLOCK_KINDS:
                coerced.append(block)
                continue
            texts: list[str] = []

            def _collect(value) -> None:
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped:
                        texts.append(stripped)
                elif isinstance(value, dict):
                    for key, child in value.items():
                        if key == "kind":
                            continue
                        _collect(child)
                elif isinstance(value, list):
                    for child in value:
                        _collect(child)

            _collect(block)
            texts = list(dict.fromkeys(texts))[:6]
            if texts:
                coerced.append({"kind": "bullets", "numbered": False,
                                "items": [{"text": text} for text in texts]})
            fixed += 1
        if coerced != blocks:
            slide["blocks"] = coerced
    return fixed


def _validate_and_repair_ppt(content: dict):
    """校验 PPT（结构 + 知识规则）并自动修复可确定性修正的问题。

    返回 (content | None, 反馈信息)：content 为修复后可通过校验的内容；为 None 时反馈用于重试。
    """
    from app.services.ppt_knowledge_service import check_ppt_against_knowledge

    slides = content.get("slides") or []
    _coerce_unknown_blocks(slides)
    # 清洗模型生成的装饰前缀。总字数不是结构合法性条件；页面承载能力
    # 由后续真实渲染、文本溢出和几何 QA 判断。
    from app.agent.slide_rendering import sanitize_slide_density
    for slide in slides:
        sanitize_slide_density(slide)
    try:
        PPTContent.model_validate(content)
    except Exception as exc:
        return None, f"结构校验失败：{str(exc)[:300]}"
    violations = check_ppt_against_knowledge(content)
    if not violations:
        return content, ""
    slides = content.get("slides") or []
    fixed = False
    for violation in violations:
        slide = next((s for s in slides if s.get("id") == violation.slide_id), None)
        if slide is None:
            continue
        rule = violation.rule_id
        if rule == "title.conclusion":
            title = (slide.get("title") or "").strip()
            if title in {"学习目标", "核心概念", "本课小结", "应用步骤", "课堂练习", "课堂总结"}:
                slide["title"] = f"本课{title}"
            else:
                slide["title"] = title + "核心要点" if title else "本课要点"
            fixed = True
        elif rule == "density.title_chars":
            slide["title"] = _clip_item(slide.get("title") or "", 30)
            fixed = True
        elif rule == "density.body_items":
            slide["body"] = (slide.get("body") or [])[:6]
            fixed = True
        elif rule == "density.item_chars":
            slide["body"] = [_clip_item(item) for item in (slide.get("body") or [])]
            fixed = True
        elif rule == "body.bullet_hardcoded":
            slide["body"] = [item.lstrip("•-* ").strip() or item for item in (slide.get("body") or [])]
            fixed = True
        elif rule == "density.speaker_notes":
            notes = slide.get("speaker_notes") or ""
            if len(notes) < 30:
                slide["speaker_notes"] = (notes or "本页要点") + "，请结合本页要点讲解，用提问确认学生理解后再进入下一环节。"
                fixed = True
        elif rule == "duration.positive":
            slide["duration_seconds"] = max(20, int(slide.get("duration_seconds") or 0))
            fixed = True
        elif rule in {"layout.valid", "layout.page_type_match"}:
            slide["layout"] = "bullet"
            fixed = True
        elif rule == "visual.suggestion_length":
            if len(slide.get("visual_suggestion") or "") < 10:
                slide["visual_suggestion"] = "用主题色区分层级，配箭头图表示关键关系"
                fixed = True
    if fixed:
        content["slides"] = slides
        try:
            PPTContent.model_validate(content)
        except Exception as exc:
            return None, f"修复后仍无法通过结构校验：{str(exc)[:300]}"
        remaining = check_ppt_against_knowledge(content)
        if remaining:
            # Knowledge-base rules describe design preferences, not PPTContent
            # validity. Keep them as diagnostics so a semantically complete,
            # schema-valid deck is never rejected for character counts, title
            # phrasing, density heuristics or other quality advice.
            return content, "；".join(v.message for v in remaining[:3])
    return content, ""


async def _generate_ppt_revision(provider, profile, knowledge_context, base_instruction, source, locks):
    """PPT 修订（质量优先）：AI 生成完整修订稿 → 锁定还原 → 校验 → 自动修复 → 一次重试。

    AI 全程参与生成修订后的完整 content_json（只改被要求的部分、遵循知识库密度规则），
    后端校验并自动修复可确定性问题，避免整体改写导致的内容膨胀。
    """
    feedback = ""
    for attempt in range(1, _PPT_REVISION_MAX_ROUNDS + 1):
        system, prompt = build_runtime_prompts(
            profile, AgentArtifactRevisionPayload.model_json_schema(), knowledge_context,
            _ppt_revision_prompt(base_instruction, source.content_json, attempt, feedback),
        )
        result = await provider.structured(system, prompt, AgentArtifactRevisionPayload)
        content = _restore_locked_paths(dict(result.content_json), source.content_json, locks)
        repaired, error = _validate_and_repair_ppt(content)
        if repaired is not None:
            return AgentArtifactRevisionPayload(content_json=repaired, assistant_reply=result.assistant_reply)
        feedback = error
    return AgentArtifactRevisionPayload(
        content_json=source.content_json,
        assistant_reply="本次修订未能通过结构校验，已保留原稿。可尝试更具体的指令或切换模型。",
    )


def _basic_video_script_from_blueprint(bp: CourseBlueprintSchema) -> dict:
    """无视频脚本时的 V2 逐字稿参考：从蓝图 timeline 生成基础场景结构。

    仅用于"完全没有视频脚本"时的逐字稿兜底（不阻塞生成）；正常路径优先
    使用真实视频脚本场景。
    """
    from app.schemas.verbatim_v2 import DEFAULT_SPEAKING_RATE_CPS

    total = float(bp.course_identity.duration_minutes * 60)
    scenes = []
    for index, segment in enumerate(bp.timeline):
        start = float(segment.start_minute * 60)
        end = float(segment.end_minute * 60)
        if end <= start:
            end = start + max(10.0, total / max(1, len(bp.timeline)))
        spoken = f"同学们好，接下来我们进入「{segment.name}」环节。{segment.purpose}"
        scenes.append({
            "id": f"SV-{index + 1:02d}",
            "sequence": index + 1,
            "title": segment.name,
            "lesson_stage_id": segment.segment_id,
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "spoken_text": spoken,
            "pedagogical_role": "概念讲解",
            "voice_direction": "自然、清晰、可信赖的中文教师讲解",
            "required_terms": [],
            "required_numbers": [],
            "required_facts": [segment.purpose],
            "production_notes": [segment.teacher_action],
        })
    return {
        "schema_version": "3.0",
        "course_info": {
            "course_title": bp.course_identity.title,
            "subject": bp.course_identity.subject,
            "grade_level": bp.course_identity.grade_level,
            "audience": bp.course_identity.audience,
            "duration_seconds": round(total),
        },
        "speaking_rate_cps": DEFAULT_SPEAKING_RATE_CPS,
        "scenes": scenes,
    }


def _basic_verbatim_from_blueprint(bp: CourseBlueprintSchema) -> VerbatimContentV2:
    """无视频脚本时的逐字稿基础稿：从蓝图 timeline 生成 V2 结构。

    共享项目记忆架构下，逐字稿不再强制等待视频脚本；缺失时先生成基础版本，
    后续视频脚本存在时可按需读取并更新。
    """
    from app.schemas.verbatim_v2 import (
        DEFAULT_SPEAKING_RATE_CPS,
        VerbatimContentV2,
        _pedagogical_action_from_role,
        verbatim_section_seconds,
        verbatim_speech_seconds,
        verbatim_word_count,
    )

    total = float(bp.course_identity.duration_minutes * 60)
    sections = []
    for index, segment in enumerate(bp.timeline):
        start = float(segment.start_minute * 60)
        end = float(segment.end_minute * 60)
        if end <= start:
            end = start + max(10.0, total / max(1, len(bp.timeline)))
        required_text = f"同学们好，接下来我们进入「{segment.name}」环节。{segment.purpose}"
        pause = round(max(0.0, min(3.0, (end - start) - verbatim_speech_seconds(required_text, DEFAULT_SPEAKING_RATE_CPS))), 2)
        sections.append({
            "id": f"VB-{index + 1:02d}",
            "scene_id": f"SV-{index + 1:02d}",
            "slide_ids": [],
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "pedagogical_action": _pedagogical_action_from_role(segment.name),
            "delivery_tone": "自然、清晰、符合学习者水平",
            "required_text": required_text,
            "optional_text": f"如果时间允许，可以结合{bp.course_identity.audience}熟悉的情境补充说明。",
            "key_emphasis": [segment.name],
            "interaction": "邀请学生用一句话概括当前要点。",
            "pause_seconds": pause,
            "word_count": verbatim_word_count(required_text),
            "estimated_duration_seconds": verbatim_section_seconds(required_text, DEFAULT_SPEAKING_RATE_CPS, pause),
        })
    return VerbatimContentV2.model_validate({
        "schema_version": "2.0",
        "course_info": {
            "course_title": bp.course_identity.title,
            "subject": bp.course_identity.subject,
            "grade_level": bp.course_identity.grade_level,
            "audience": bp.course_identity.audience,
            "duration_seconds": round(total),
        },
        "speaking_rate_cps": DEFAULT_SPEAKING_RATE_CPS,
        "source_versions": {},
        "sections": sections,
    })


async def _generate_initial(db, course: CourseProject, task: CourseTask, blueprint: CourseBlueprint, run: GenerationRun):
    bp = CourseBlueprintSchema.model_validate(blueprint.content_json)
    kind = task.task_type
    profile, provider, config = await _profile_provider(db, course, task)
    if kind == "lesson_plan":
        # 新生成教学设计直接写 V2（确定性示例）；V1 仅历史 Artifact 保留。
        from app.schemas.lesson_plan import make_lesson_plan_v2

        mock = make_lesson_plan_v2(bp)
        schema = LessonPlanContentV2
    elif kind == "ppt":
        preferred_template = resolve_ppt_template(
            normalize_model_preferences(config.preferences_json).get("default_ppt_template") if config else None,
        )["id"]
        mock = make_ppt(bp, preferred_template)
        schema = PPTContent
    elif kind == "task_sheet":
        mock = make_task_sheet(bp)
        schema = TaskSheetContent
    elif kind == "exercise":
        mock = make_exercises(bp)
        schema = ExerciseContent
    elif kind == "video_script":
        # 共享项目记忆：教学设计是可选参考，缺失时用蓝图生成基础脚本（不阻塞）。
        lesson_artifact = await _latest_artifact(db, course.id, "lesson_plan")
        from app.schemas.lesson_plan import lesson_plan_v1_from_any

        if lesson_artifact:
            lesson_plan = lesson_plan_v1_from_any(lesson_artifact.content_json)
        else:
            lesson_plan = make_lesson_plan(bp)
        mock = make_seedance_video_script(bp, lesson_plan)
        schema = SeedanceVideoScriptContent
    else:
        script_artifact = await _latest_artifact(db, course.id, "video_script")
        schema_version = (script_artifact.content_json or {}).get("schema_version") if script_artifact else None
        if script_artifact and schema_version in {"3.0", "4.0"}:
            from app.schemas.video_script_v4 import seedance_video_script_for_generation
            from app.schemas.verbatim_v2 import make_seedance_verbatim_v2

            script = seedance_video_script_for_generation(script_artifact.content_json)
            script_data = script.model_dump() if hasattr(script, "model_dump") else script
            mock = make_seedance_verbatim_v2(bp, script_data)
        elif script_artifact:
            # 旧版脚本：V1 逐字稿作为过渡，首次修改时由 Agent 升级为 V2。
            ppt_artifact = await _latest_artifact(db, course.id, "ppt")
            if ppt_artifact:
                mock = make_verbatim(
                    bp, PPTContent.model_validate(ppt_artifact.content_json),
                    VideoScriptContent.model_validate(script_artifact.content_json),
                )
            else:
                mock = make_seedance_verbatim_v2(bp, _basic_video_script_from_blueprint(bp))
        else:
            # 无视频脚本：基于蓝图生成基础逐字稿（不阻塞）。
            mock = _basic_verbatim_from_blueprint(bp)
        schema = VerbatimContentV2
    knowledge_context, source_versions = await build_project_knowledge_context(
        db, task, blueprint.content_json, blueprint.version, profile.context_json,
        config.context_window_tokens if config else None, run=run, provider=provider,
    )
    if isinstance(provider, MockProvider):
        value = mock
    else:
        instruction = "生成本任务文件首稿。"
        if kind == "ppt":
            instruction += _ppt_template_instruction(getattr(mock, "theme", None))
        system, prompt = build_runtime_prompts(
            profile, schema.model_json_schema(), knowledge_context, instruction,
        )
        try:
            value = await provider.structured(system, prompt, schema)
        except Exception as exc:  # noqa: BLE001
            # First drafts already have a project-specific, schema-valid base
            # generated from the approved blueprint.  A model occasionally
            # returns truncated/empty JSON for the very large video-script
            # schema; that must not make project initialization fail.
            from pydantic import ValidationError

            if not isinstance(exc, ValidationError) and run.trigger_type != "initial":
                raise
            logger.warning(
                "Initial %s model generation failed; using blueprint draft",
                kind,
                extra={
                    "course_id": course.id,
                    "run_id": run.id,
                    "error_type": type(exc).__name__,
                },
            )
            value = mock
    if kind == "ppt":
        value.theme = mock.theme
    return value, resolved_model_name(provider, config), profile, source_versions


async def _deterministic_initial_result(
    db, course: CourseProject, task: CourseTask, blueprint: CourseBlueprint,
):
    """Build a publishable first draft without calling an external model.

    This is the last-resort path for an initial Agent pipeline: a malformed
    streamed decision, provider timeout, or pipeline exception must not leave a
    newly created project with no usable files.  The same project-specific
    generators used by MockProvider are used here, so the result still follows
    the approved blueprint and normal schema/QA/save flow.
    """
    from app.services.ppt_pipeline_service import PipelineRunResult
    from app.schemas.lesson_plan import make_lesson_plan_v2

    bp = normalize_blueprint_references(CourseBlueprintSchema.model_validate(blueprint.content_json))
    profile, provider, config = await _profile_provider(db, course, task)
    if task.task_type == "lesson_plan":
        value = make_lesson_plan_v2(bp)
    elif task.task_type == "ppt":
        template_id = resolve_ppt_template(
            normalize_model_preferences(config.preferences_json).get("default_ppt_template") if config else None,
        )["id"]
        value = make_ppt(bp, template_id)
    elif task.task_type == "task_sheet":
        value = make_task_sheet(bp)
    elif task.task_type == "exercise":
        value = make_exercises(bp)
    elif task.task_type == "video_script":
        value = make_seedance_video_script(bp, make_lesson_plan(bp))
    elif task.task_type == "verbatim":
        value = _basic_verbatim_from_blueprint(bp)
    else:
        raise RuntimeError(f"不支持为 {task.task_type} 创建确定性首稿")
    return PipelineRunResult(
        content=value.model_dump(),
        model_name="lessonforge-deterministic-fallback-v1",
        profile=profile,
        provider=provider,
        locks=[],
        source_versions={},
        change_summary="首次生成（确定性兜底）",
        runtime=None,
    )


def _locked_value(content: dict, path: str):
    if path in {"", "$"}:
        return content
    value = content
    for part in [part for part in re.split(r"\.|\[|\]", path.removeprefix("$.")) if part]:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, list):
            value = next((entry for entry in value if isinstance(entry, dict) and entry.get("id") == part), None)
        else:
            return None
    return value


async def _generate_revision(db, course: CourseProject, task: CourseTask, run: GenerationRun, source: Artifact, blueprint: CourseBlueprint):
    message = await db.scalar(select(AgentMessage).where(
        AgentMessage.run_id == run.id,
        AgentMessage.role == "user",
    ).order_by(AgentMessage.created_at.desc()))
    if not message:
        raise RuntimeError("未找到本次教师修改指令")
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
    if any(lock.json_path in {"", "$"} for lock in locks):
        raise RuntimeError("当前任务文件已整体锁定")
    profile, provider, config = await _profile_provider(db, course, task)
    knowledge_context, source_versions = await build_project_knowledge_context(
        db, task, blueprint.content_json, blueprint.version, profile.context_json,
        config.context_window_tokens if config else None, run=run, provider=provider,
    )
    version = source.version + 1
    if isinstance(provider, MockProvider):
        if task.task_type == "task_sheet" and source.content_json.get("schema_version") == "3.0":
            # V3 动态任务单：旧单次路径原样保留（动态流水线负责 V3 修改）。
            content = dict(source.content_json)
        elif task.task_type in {"task_sheet", "exercise"} and source.content_json.get("schema_version") != "2.0":
            factory = make_task_sheet if task.task_type == "task_sheet" else make_exercises
            content = factory(CourseBlueprintSchema.model_validate(blueprint.content_json)).model_dump()
        elif task.task_type == "video_script" and source.content_json.get("schema_version") not in {"3.0", "4.0"}:
            lesson_artifact = await _latest_artifact(db, course.id, "lesson_plan")
            from app.schemas.lesson_plan import lesson_plan_v1_from_any

            # 共享项目记忆：教学设计缺失时用蓝图兜底（不阻塞升级）。
            if lesson_artifact:
                lesson_plan = lesson_plan_v1_from_any(lesson_artifact.content_json)
            else:
                lesson_plan = make_lesson_plan(CourseBlueprintSchema.model_validate(blueprint.content_json))
            content = make_seedance_video_script(
                CourseBlueprintSchema.model_validate(blueprint.content_json),
                lesson_plan,
            ).model_dump()
        elif task.task_type == "video_script" and source.content_json.get("schema_version") == "3.0":
            # 保持 V3 幂等：旧单次路径对 V3 原样保留（动态流水线负责 V4 升级）
            content = dict(source.content_json)
        elif task.task_type == "verbatim" and source.content_json.get("schema_version") != "2.0":
            script_artifact = await _latest_artifact(db, course.id, "video_script")
            script_raw = None
            if script_artifact and (script_artifact.content_json or {}).get("schema_version") in {"3.0", "4.0"}:
                from app.schemas.video_script_v4 import seedance_video_script_for_generation

                script_raw = seedance_video_script_for_generation(script_artifact.content_json).model_dump()
            from app.schemas.verbatim_v2 import upgrade_verbatim_v2

            content = upgrade_verbatim_v2(source.content_json, script_raw).model_dump()
        else:
            content = dict(source.content_json)
        conflict_note = ""
        if knowledge_context.get("conflicts"):
            conflict_note = " 检测到兄弟产物与蓝图的引用冲突，已按蓝图保留合法编号。"
        revision = AgentArtifactRevisionPayload(
            content_json=content,
            assistant_reply=f"已根据你的要求创建{TASK_SPEC_BY_TYPE[task.task_type][1]} V{version}，原版本仍可在版本历史中恢复。{conflict_note}",
        )
    else:
        history = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.course_id == course.id,
            AgentMessage.module_type == task.task_type,
        ).order_by(AgentMessage.created_at.desc()).limit(12)))
        schema = TASK_SCHEMAS[task.task_type]
        if task.task_type == "ppt":
            # PPT 修订：AI 生成完整修订稿 → 校验 → 自动修复 → 重试（质量优先）。
            # 当前内容由修订函数注入最新状态，这里只传稳定上下文。
            base_instruction = (
                "最近对话：\n" + json.dumps([{"role": x.role, "content": x.content} for x in reversed(history)], ensure_ascii=False)
                + "\n锁定路径：\n" + json.dumps([x.json_path for x in locks], ensure_ascii=False)
                + "\n教师指令：\n" + message.content
                + "\ncontent_json 必须符合：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            ) + _ppt_template_instruction((source.content_json or {}).get("theme"))
            revision = await _generate_ppt_revision(
                provider, profile, knowledge_context, base_instruction, source, locks,
            )
        else:
            instruction = (
                "当前结构化内容：\n" + json.dumps(source.content_json, ensure_ascii=False)
                + "\n最近对话：\n" + json.dumps([{"role": x.role, "content": x.content} for x in reversed(history)], ensure_ascii=False)
                + "\n锁定路径：\n" + json.dumps([x.json_path for x in locks], ensure_ascii=False)
                + "\n教师指令：\n" + message.content
                + "\ncontent_json 必须符合：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            )
            system, prompt = build_runtime_prompts(
                profile, AgentArtifactRevisionPayload.model_json_schema(), knowledge_context, instruction,
            )
            revision = await provider.structured(system, prompt, AgentArtifactRevisionPayload)
    return revision, message, resolved_model_name(provider, config), profile, provider, locks, source_versions


async def _generate_context_sync(
    db,
    course: CourseProject,
    task: CourseTask,
    source: Artifact,
    blueprint: CourseBlueprint,
    run: GenerationRun | None = None,
):
    profile, provider, config = await _profile_provider(db, course, task)
    knowledge_context, source_versions = await build_project_knowledge_context(
        db, task, blueprint.content_json, blueprint.version, profile.context_json,
        config.context_window_tokens if config else None, run=run, provider=provider,
    )
    schema = TASK_SCHEMAS[task.task_type]
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
    # 历史脚本升级为 Seedance V3；只使用已确认蓝图和教学设计，绝不读取 PPT。
    if task.task_type == "video_script" and source.content_json.get("schema_version") not in {"3.0", "4.0"}:
        lesson_artifact = await _latest_artifact(db, course.id, "lesson_plan")
        from app.schemas.lesson_plan import lesson_plan_v1_from_any

        # 共享项目记忆：教学设计缺失时用蓝图兜底（不阻塞升级）。
        if lesson_artifact:
            lesson_plan = lesson_plan_v1_from_any(lesson_artifact.content_json)
        else:
            lesson_plan = make_lesson_plan(CourseBlueprintSchema.model_validate(blueprint.content_json))
        value = make_seedance_video_script(
            CourseBlueprintSchema.model_validate(blueprint.content_json),
            lesson_plan,
        )
        model_name = "deterministic-to-seedance-v3"
    elif isinstance(provider, MockProvider):
        if task.task_type in {"task_sheet", "exercise"} and source.content_json.get("schema_version") != "2.0":
            factory = make_task_sheet if task.task_type == "task_sheet" else make_exercises
            value = factory(CourseBlueprintSchema.model_validate(blueprint.content_json))
        elif task.task_type == "verbatim" and source.content_json.get("schema_version") != "2.0":
            script_artifact = await _latest_artifact(db, course.id, "video_script")
            script_raw = None
            if script_artifact and (script_artifact.content_json or {}).get("schema_version") in {"3.0", "4.0"}:
                from app.schemas.video_script_v4 import seedance_video_script_for_generation

                script_raw = seedance_video_script_for_generation(script_artifact.content_json).model_dump()
            from app.schemas.verbatim_v2 import upgrade_verbatim_v2

            value = upgrade_verbatim_v2(source.content_json, script_raw)
        else:
            value = schema.model_validate(source.content_json)
        model_name = resolved_model_name(provider, config)
    else:
        instruction = (
            "请在保留当前文件有效内容的基础上同步最新项目知识；不得无故改写未受影响字段。\n"
            "当前待同步文件：\n" + json.dumps(source.content_json, ensure_ascii=False)
            + "\n锁定路径：\n" + json.dumps([item.json_path for item in locks], ensure_ascii=False)
        )
        system, prompt = build_runtime_prompts(
            profile, schema.model_json_schema(), knowledge_context, instruction,
        )
        value = await provider.structured(system, prompt, schema)
        model_name = resolved_model_name(provider, config)
    return value, model_name, profile, source_versions, locks


async def _create_streaming_reply(run_id: str) -> str:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
        if not run or not task:
            raise RuntimeError("任务运行不存在")
        reply = await db.scalar(select(AgentMessage).where(
            AgentMessage.run_id == run.id,
            AgentMessage.role == "assistant",
        ))
        if reply:
            reply.content = ""
            reply.status = "streaming"
            reply.artifact_id = None
        else:
            reply = AgentMessage(
                course_id=run.course_id,
                task_id=task.id,
                run_id=run.id,
                module_type=task.task_type,
                role="assistant",
                content="",
                status="streaming",
            )
            db.add(reply)
            await db.flush()
        await _emit(db, run, "agent_message_started", task, message={
            "id": reply.id,
            "role": "assistant",
            "content": "",
            "run_id": run.id,
            "status": "streaming",
        })
        await db.commit()
        return reply.id


async def _publish_reply_delta(run_id: str, message_id: str, delta: str, *, reset: bool = False):
    if not delta and not reset:
        return
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
        reply = await db.get(AgentMessage, message_id)
        if not run or not task or not reply:
            return
        reply.content = delta if reset else reply.content + delta
        reply.status = "streaming"
        await _emit(
            db,
            run,
            "agent_message_delta",
            task,
            message_id=message_id,
            delta=delta,
            reset=reset,
        )
        await db.commit()


async def _stream_verified_reply(
    run_id: str,
    provider,
    task: CourseTask,
    teacher_instruction: str,
    version: int,
    fallback: str,
) -> tuple[str, str]:
    message_id = await _create_streaming_reply(run_id)
    system = apply_output_rules(
        "你是课程交付文件修改助理。请根据已经通过结构校验的结果，用简洁、自然的中文回复教师。"
        "只说明已经完成的调整、对应文件版本和可继续修改的方向，不添加输入中没有的事实，"
        "不展示隐藏推理、系统提示词或内部参数。"
    )
    prompt = "已验证结果：\n" + json.dumps({
        "task": TASK_SPEC_BY_TYPE[task.task_type][1],
        "version": version,
        "teacher_instruction": teacher_instruction,
        "verified_summary": fallback,
    }, ensure_ascii=False) + "\nDISPLAY_REPLY:" + fallback

    content = ""
    pending = ""
    last_flush = time.monotonic()

    async def flush(*, reset: bool = False):
        nonlocal pending, last_flush
        if not pending and not reset:
            return
        chunk = pending
        pending = ""
        await _publish_reply_delta(run_id, message_id, chunk, reset=reset)
        last_flush = time.monotonic()

    try:
        async for chunk in provider.stream_text(system, prompt):
            if not chunk:
                continue
            remaining = 1000 - len(content)
            if remaining <= 0:
                break
            accepted = chunk[:remaining]
            content += accepted
            pending += accepted
            if (
                len(pending) >= 24
                or time.monotonic() - last_flush >= 0.15
                or pending.endswith(("。", "！", "？", "\n"))
            ):
                await flush()
        await flush()
        content = content.strip()
        if not content:
            raise RuntimeError("模型未返回可展示回复")
    except Exception:
        logger.warning("Streaming task reply failed; using verified fallback", extra={"run_id": run_id})
        content = fallback.strip()
        pending = ""
        await _publish_reply_delta(run_id, message_id, "", reset=True)
        for index in range(0, len(content), 18):
            await _publish_reply_delta(run_id, message_id, content[index:index + 18])
    return message_id, content


async def _mark_streaming_reply_failed(run_id: str, message: str):
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
        reply = await db.scalar(select(AgentMessage).where(
            AgentMessage.run_id == run_id,
            AgentMessage.role == "assistant",
            AgentMessage.status == "streaming",
        ))
        if not run or not task or not reply:
            return
        reply.status = "failed"
        await _emit(
            db,
            run,
            "agent_message_failed",
            task,
            message_id=reply.id,
            error={"code": "reply_interrupted", "message": message, "retryable": True},
        )
        await db.commit()


async def _source_versions(db, task: CourseTask) -> dict[str, int]:
    result = {}
    for dependency in task.dependency_types_json:
        artifact = await _latest_artifact(db, task.course_id, dependency)
        if artifact:
            result[dependency] = artifact.version
    return result


async def _mark_dependents_stale(db, source_task: CourseTask, source_version: int):
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == source_task.course_id)))
    stale_tasks = []
    for task in tasks:
        if source_task.task_type not in task.dependency_types_json:
            continue
        if not task.current_artifact_id:
            if task.task_type == "video_generation" and task.status == "ready_to_generate":
                task.status = "waiting_dependency"
                task.progress = 0
                task.error_json = None
                stale_tasks.append(task)
            continue
        artifact = await db.get(Artifact, task.current_artifact_id)
        if artifact and (artifact.source_versions_json or {}).get(source_task.task_type) != source_version:
            task.status = "stale"
            task.error_json = None
            stale_tasks.append(task)
    return stale_tasks


async def register_artifact_version(db, artifact: Artifact, invalidate_dependents: bool = True):
    """Make a teacher-created or legacy Agent version the task's current file."""
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == artifact.course_id,
        CourseTask.task_type == artifact.artifact_type,
    ))
    if not task:
        return
    if artifact.artifact_type == "video_generation" and not is_publishable_video_artifact(artifact):
        task.current_artifact_id = None
        task.status = "waiting_dependency"
        task.progress = 0
        task.error_json = None
        return
    task.current_artifact_id = artifact.id
    if task.current_agent_profile_id and artifact.agent_profile_id != task.current_agent_profile_id:
        task.status = "stale"
    else:
        task.status = "review" if artifact.status != "approved" else "approved"
    task.progress = 100
    task.error_json = None
    task.completed_at = utcnow()
    # 共享项目记忆：教师/旧路径创建的新版本同样索引进项目记忆并推进版本。
    if artifact.artifact_type in CONTENT_TASK_TYPES:
        from app.services.project_knowledge_service import bump, index_artifact

        await index_artifact(db, artifact, created_by="teacher")
        memory_revision = await bump(
            db, artifact.course_id, f"{TASK_SPEC_BY_TYPE[artifact.artifact_type][1]} 发布 V{artifact.version}",
            source_type="artifact", source_id=artifact.id, created_by="teacher",
        )
        artifact.memory_revision_created = memory_revision
        run = await db.scalar(select(GenerationRun).where(
            GenerationRun.course_task_id == task.id,
        ).order_by(GenerationRun.created_at.desc()).limit(1))
        if run:
            await _emit(
                db, run, "artifact.published", task, status=task.status,
                artifact=artifact_payload(artifact), memory_revision=memory_revision,
            )
            await _emit(
                db, run, "project_memory.updated", task, status=task.status,
                memory_revision=memory_revision,
                change_reason=f"{TASK_SPEC_BY_TYPE[artifact.artifact_type][1]} 发布 V{artifact.version}",
            )
    if invalidate_dependents:
        await _mark_dependents_stale(db, task, artifact.version)


async def _refresh_quality(db, course: CourseProject, blueprint: CourseBlueprint):
    resources = {}
    for task_type in CONTENT_TASK_TYPES:
        artifact = await _latest_artifact(db, course.id, task_type)
        if not artifact:
            return
        resources[task_type] = artifact.content_json
    issues = validate_resources(CourseBlueprintSchema.model_validate(blueprint.content_json), resources)
    exercise_review = (resources.get("exercise") or {}).get("review_summary") or {}
    for note in exercise_review.get("notes", []):
        issues.append({
            "severity": "minor",
            "artifact_type": "exercise",
            "location": "$.review_summary.notes",
            "dimension": "model_review",
            "description": note,
            "evidence": note,
            "suggestion": "请教师复核该题，或在练习 Agent 中继续修改。",
            "target_agent": "exercise_agent",
            "required_action": "revise",
        })
    report = QualityReport(
        course_id=course.id,
        score=max(0, 100 - len(issues) * 8),
        dimensions_json={"structure": 5, "alignment": 5 if not issues else 4},
        summary="已完成结构、引用、时长、目标覆盖和题目结构检查。",
    )
    db.add(report)
    await db.flush()
    # 各校验器问题字典字段不完全一致（如任务单 V3 携带 path/id/target_role），
    # 投影为 QualityIssue 的持久化字段，避免未知列导致整条任务失败。
    quality_columns = {
        "artifact_type", "severity", "location", "dimension", "description",
        "evidence", "suggestion", "target_agent", "required_action",
    }
    for issue in issues:
        db.add(QualityIssue(report_id=report.id, **{
            key: value for key, value in issue.items() if key in quality_columns
        }))
    # 共享项目记忆：QA 结论进入项目记忆（同一事务，先写后 bump）。
    from app.services.project_knowledge_service import bump, index_qa

    await index_qa(
        db, course.id, report.id, report.score, report.summary,
        issues=[{k: item.get(k) for k in ("artifact_type", "severity", "description")} for item in issues],
        created_by="qa",
    )
    await bump(
        db, course.id, "质量检查完成", source_type="qa", source_id=report.id, created_by="qa",
    )
    for kind, content, markdown, model in (
        ("quality_report", {"score": report.score, "summary": report.summary, "issues": issues}, f"# 质量报告\n\n{report.summary}\n\n- 综合分数：{report.score}\n- 问题数量：{len(issues)}", "rules"),
        ("citation_report", {"source_refs": blueprint.content_json.get("source_refs", [])}, "# 引用来源\n\n" + ("\n".join(f"- {ref}" for ref in blueprint.content_json.get("source_refs", [])) or "本课程未引用上传材料片段。"), "deterministic"),
    ):
        version = (await db.scalar(select(func.max(Artifact.version)).where(Artifact.course_id == course.id, Artifact.artifact_type == kind)) or 0) + 1
        db.add(Artifact(course_id=course.id, artifact_type=kind, version=version, blueprint_version=blueprint.version, content_json=content, content_markdown=markdown, model_name=model, prompt_version="v2", change_summary="随任务文件自动更新"))


async def _refresh_course_status(db, course: CourseProject):
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course.id)))
    content_tasks = [item for item in tasks if item.task_type in CONTENT_TASK_TYPES]
    statuses = {item.status for item in content_tasks}
    if content_tasks and statuses == {"approved"}:
        course.status = "completed"
    elif "failed" in statuses:
        course.status = "needs_attention"
    elif statuses & {"queued", "running", "waiting_dependency"}:
        course.status = "resource_generating"
    else:
        course.status = "teacher_review"


async def _apply_pending_video_resolution(db, course: CourseProject, pipeline_runtime) -> bool:
    """把复合视频脚本指令的设置更新并入成功终态事务。"""
    patch = getattr(pipeline_runtime, "pending_video_settings", None)
    if patch is None:
        resolution = str(getattr(pipeline_runtime, "pending_video_resolution", "") or "")
        patch = VideoGenerationSettingsPatch(preferred_resolution=resolution) if resolution else None
    result_status = str(getattr(pipeline_runtime, "result_status", "") or "")
    if patch is None or result_status not in {"applied", "no_change", "settings_applied", "settings_unchanged"}:
        return False
    update = await apply_video_generation_settings(
        db,
        course,
        patch,
    )
    pipeline_runtime.video_resolution_update = update
    return True


async def execute_task_run(run_id: str):
    current_phase = "preparing"
    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            course = await db.get(CourseProject, run.course_id) if run else None
            if not run or not task or not course:
                return
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == course.id,
                CourseBlueprint.version == course.current_blueprint_version,
            ))
            if not blueprint or blueprint.status != "approved":
                raise RuntimeError("课程内部规划尚未完成")
            blueprint_schema = normalize_blueprint_references(
                CourseBlueprintSchema.model_validate(blueprint.content_json)
            )

            run.status = "running"
            run.started_at = utcnow()
            run.progress = 10
            task.status = "running"
            task.progress = 10
            task.started_at = task.started_at or utcnow()
            await _emit(db, run, "task_status_changed", task, status="running", progress=10)
            await db.commit()

            await _publish_activity(run_id, "preparing", 10)
            await _publish_activity(run_id, "preparing", 16, "completed")
            current_phase = "analyzing"
            await _publish_activity(run_id, "analyzing", 20)

            source = await _latest_artifact(db, course.id, task.task_type)
            revision = None
            user_message = None
            provider = None
            pipeline_runtime = None
            locks = []
            await _publish_activity(run_id, "analyzing", 26, "completed")
            current_phase = "generating"
            await _publish_activity(run_id, "generating", 30)
            use_lesson_plan_pipeline = (
                task.task_type == "lesson_plan" and get_settings().lesson_plan_agent_runtime_enabled
            )
            use_task_sheet_pipeline = (
                task.task_type == "task_sheet" and get_settings().task_sheet_agent_runtime_enabled
            )
            use_video_script_pipeline = (
                task.task_type == "video_script"
                and run.trigger_type == "message"
                and get_settings().video_script_agent_runtime_enabled
            )
            use_verbatim_pipeline = (
                task.task_type == "verbatim" and get_settings().verbatim_agent_runtime_enabled
            )
            use_exercise_pipeline = (
                task.task_type == "exercise" and get_settings().exercise_agent_runtime_enabled
            )
            if task.task_type == "ppt" or use_lesson_plan_pipeline or use_task_sheet_pipeline or use_video_script_pipeline or use_verbatim_pipeline or use_exercise_pipeline:
                # PPT：多 Agent 流水线（多次 LLM 调用 + 工具调用 + QA 修订闭环）
                # 教学设计 V2 / 任务单 V3 / 视频脚本 V4 / 逐字稿 V2 / 课后练习 V2：
                # 动态工具化流水线（意图识别 + 工具修改候选稿 + QA 返修 + 流式时间线）
                if task.task_type == "ppt":
                    from app.services.ppt_pipeline_service import run_ppt_pipeline

                    pipeline_runner = run_ppt_pipeline(db, course, task, run, blueprint)
                elif use_lesson_plan_pipeline:
                    from app.services.lesson_plan_pipeline_service import run_lesson_plan_pipeline

                    pipeline_runner = run_lesson_plan_pipeline(db, course, task, run, blueprint)
                elif use_video_script_pipeline:
                    from app.services.video_script_pipeline_service import run_video_script_pipeline

                    pipeline_runner = run_video_script_pipeline(db, course, task, run, blueprint)
                elif use_verbatim_pipeline:
                    from app.services.verbatim_pipeline_service import run_verbatim_pipeline

                    pipeline_runner = run_verbatim_pipeline(db, course, task, run, blueprint)
                elif use_exercise_pipeline:
                    from app.services.exercise_pipeline_service import run_exercise_pipeline

                    pipeline_runner = run_exercise_pipeline(db, course, task, run, blueprint)
                else:
                    from app.services.task_sheet_pipeline_service import run_task_sheet_pipeline

                    pipeline_runner = run_task_sheet_pipeline(db, course, task, run, blueprint)
                try:
                    generated, generation_elapsed = await _run_with_generation_heartbeat(
                        run_id,
                        pipeline_runner,
                    )
                    result = generated
                except Exception:
                    if run.trigger_type != "initial":
                        raise
                    # Initial generation must be recoverable even when a model
                    # returns malformed streamed JSON or an Agent pipeline
                    # aborts before producing a candidate.  Roll back partial
                    # pipeline writes, then continue through the same publish
                    # and QA path with a deterministic project draft.
                    logger.exception(
                        "Initial Agent pipeline failed; using deterministic draft",
                        extra={"course_id": course.id, "run_id": run.id, "task_type": task.task_type},
                    )
                    await db.rollback()
                    run = await db.get(GenerationRun, run_id)
                    task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
                    course = await db.get(CourseProject, run.course_id) if run else None
                    blueprint = await db.scalar(select(CourseBlueprint).where(
                        CourseBlueprint.course_id == course.id,
                        CourseBlueprint.version == course.current_blueprint_version,
                    )) if course else None
                    if not run or not task or not course or not blueprint:
                        raise RuntimeError("确定性首稿回退时任务上下文不存在")
                    blueprint_schema = normalize_blueprint_references(
                        CourseBlueprintSchema.model_validate(blueprint.content_json)
                    )
                    result = await _deterministic_initial_result(db, course, task, blueprint)
                    generation_elapsed = 0
                content = result.content
                revision = result.revision
                user_message = result.user_message
                model_name = result.model_name
                profile = result.profile
                provider = result.provider
                locks = result.locks
                source_versions = result.source_versions
                change_summary = result.change_summary
                pipeline_runtime = result.runtime
                skip_publish = result.skip_publish
            elif run.trigger_type == "message":
                if not source:
                    raise RuntimeError("任务文件尚未生成")
                generated, generation_elapsed = await _run_with_generation_heartbeat(
                    run_id,
                    _generate_revision(db, course, task, run, source, blueprint),
                )
                revision, user_message, model_name, profile, provider, locks, source_versions = generated
                content = revision.content_json
                change_summary = f"Agent 对话修改：{user_message.content[:80]}"
            elif run.trigger_type == "sync_context":
                if not source:
                    raise RuntimeError("任务文件尚未生成，无法同步项目上下文")
                generated, generation_elapsed = await _run_with_generation_heartbeat(
                    run_id,
                    _generate_context_sync(db, course, task, source, blueprint, run),
                )
                value, model_name, profile, source_versions, locks = generated
                content = value.model_dump()
                change_summary = "上下文同步生成"
            else:
                generated, generation_elapsed = await _run_with_generation_heartbeat(
                    run_id,
                    _generate_initial(db, course, task, blueprint, run),
                )
                value, model_name, profile, source_versions = generated
                content = value.model_dump()
                markdown = to_markdown(task.task_type, value)
                change_summary = (
                    "上下文同步生成"
                    if run.trigger_type in {"sync_dependencies", "sync_context"}
                    else "首次生成"
                )

            # 共享项目记忆：记录本次运行实际读取的上下文快照（版本 + 可用来源清单）。
            # 新前端消费该事件展示"本次使用项目记忆 V{n}"；旧前端忽略未知事件。
            await _emit(
                db,
                run,
                "context.snapshot_created",
                task,
                status=task.status,
                memory_revision=run.memory_revision or 0,
                context_manifest=run.context_manifest_json or {},
                context_hash=run.context_hash or "",
            )
            # Close the read transaction before independently committed stream events
            # continue updating the same SQLite database.
            await db.commit()
            await _publish_activity(
                run_id,
                "generating",
                74,
                "completed",
                elapsed_ms=generation_elapsed,
            )

            if (task.task_type == "ppt" or use_lesson_plan_pipeline or use_task_sheet_pipeline or use_video_script_pipeline or use_verbatim_pipeline or use_exercise_pipeline) and skip_publish:
                # A safe no-op is a successful request resolution, not a new
                # domain version. Keep the official Artifact pointer and close
                # the run with an explicit no_change terminal result.
                # 人工确认等待（needs_confirmation）：run 保持 paused，不终结；
                # 确认接口从同一 GenerationRun 的 checkpoint 恢复。
                if result.keep_paused:
                    task.status = "paused"
                    task.progress = 90
                    run.status = "paused"
                    run.progress = 90
                    stored_user_message = await db.get(AgentMessage, user_message.id) if user_message else None
                    if stored_user_message:
                        stored_user_message.status = "completed"
                    await db.commit()
                    if pipeline_runtime is not None and getattr(pipeline_runtime, "emitter", None) is not None:
                        await pipeline_runtime.emitter.task_paused(
                            reason="等待教师人工确认", checkpoint_step=pipeline_runtime.current_agent_key or "confirmation",
                        )
                    return
                if use_video_script_pipeline:
                    await _apply_pending_video_resolution(db, course, pipeline_runtime)
                await db.commit()
                if task.task_type == "ppt":
                    from app.services.ppt_pipeline_service import complete_ppt_pipeline_after_publish
                    complete = complete_ppt_pipeline_after_publish
                elif use_lesson_plan_pipeline:
                    from app.services.lesson_plan_pipeline_service import complete_lesson_plan_pipeline_after_publish
                    complete = complete_lesson_plan_pipeline_after_publish
                elif use_video_script_pipeline:
                    from app.services.video_script_pipeline_service import complete_video_script_pipeline_after_publish
                    complete = complete_video_script_pipeline_after_publish
                elif use_verbatim_pipeline:
                    from app.services.verbatim_pipeline_service import complete_verbatim_pipeline_after_publish
                    complete = complete_verbatim_pipeline_after_publish
                elif use_exercise_pipeline:
                    from app.services.exercise_pipeline_service import complete_exercise_pipeline_after_publish
                    complete = complete_exercise_pipeline_after_publish
                else:
                    from app.services.task_sheet_pipeline_service import complete_task_sheet_pipeline_after_publish
                    complete = complete_task_sheet_pipeline_after_publish
                await complete(
                    pipeline_runtime, source.id if source is not None else "",
                )
                await db.rollback()
                run = await db.get(GenerationRun, run_id)
                task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
                course = await db.get(CourseProject, run.course_id) if run else None
                if not run or not task or not course:
                    raise RuntimeError("完成无变更运行时任务上下文不存在")
                final_status = "review" if task.current_agent_profile_id == profile.id else "stale"
                task.status = final_status
                task.progress = 100
                task.active_run_id = None
                task.error_json = None
                task.completed_at = utcnow()
                run.status = "completed"
                run.progress = 100
                run.finished_at = utcnow()
                stored_user_message = await db.get(AgentMessage, user_message.id) if user_message else None
                if stored_user_message:
                    stored_user_message.status = "completed"
                await _refresh_course_status(db, course)
                await _emit(
                    db, run, "task_activity_updated", task,
                    status=final_status, progress=100, phase="completed",
                    phase_label=PHASE_LABELS["completed"],
                    detail="润色检查完成，当前版本无需安全修改。",
                    phase_status="completed", elapsed_ms=0,
                )
                await _emit(db, run, "task_status_changed", task, status=final_status, progress=100)
                await db.commit()
                return

            current_phase = "validating"
            await _publish_activity(run_id, "validating", 76)
            visual_notes: list[str] = []
            if task.task_type == "ppt":
                # 普通修改禁止模型暗改模板；显式模板切换则必须保留 Runtime 已通过
                # 完整性门禁的目标模板，不能在保存前又覆写回源版本主题。
                if pipeline_runtime and pipeline_runtime.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}:
                    trusted_theme = pipeline_runtime.preferred_template
                else:
                    trusted_theme = (source.content_json or {}).get("theme") if source else content.get("theme")
                content = {**content, "theme": resolve_ppt_template(trusted_theme)["id"]}
            if task.task_type == "exercise" and not use_exercise_pipeline:
                # 旧路径（开关关闭）：视觉处理 + 降级在 pipeline 外后置执行；
                # agentic 流水线路径的视觉决策/降级已在 pipeline 内完成。
                content, _, pipeline_notes = await process_exercise_visuals(db, course, run, content)
                content, degraded_notes = degrade_unreviewed_visuals(content)
                visual_notes = [*pipeline_notes, *degraded_notes]
            if task.task_type == "lesson_plan":
                # V1/V2 按 schema_version 分派校验；V2 候选稿在保存前再跑统一质量门禁。
                lesson_issues = validate_lesson_plan(
                    blueprint_schema,
                    content,
                    [lock.json_path for lock in locks],
                )
                blocking = [item for item in lesson_issues if item["severity"] in {"critical", "major"}]
                if blocking:
                    if run.trigger_type == "initial":
                        # A model/Agent can produce schema-valid content whose
                        # objective-to-stage graph is incomplete.  Initialization
                        # must still deliver a usable first draft; the deterministic
                        # draft preserves the approved blueprint and is rechecked
                        # by the same gate before publish.
                        from app.schemas.lesson_plan import make_lesson_plan_v2

                        logger.warning(
                            "Initial lesson plan failed semantic QA; using blueprint draft",
                            extra={"course_id": course.id, "run_id": run.id},
                        )
                        content = make_lesson_plan_v2(blueprint_schema).model_dump()
                        lesson_issues = validate_lesson_plan(blueprint_schema, content, [])
                        blocking = [item for item in lesson_issues if item["severity"] in {"critical", "major"}]
                    if blocking:
                        raise TaskValidationError(f"教学设计校验未通过：{blocking[0]['description']}")
            if task.task_type == "lesson_plan" and (content or {}).get("schema_version") == "2.0":
                validated_model = LessonPlanContentV2.model_validate(content)
            elif task.task_type == "task_sheet" and (content or {}).get("schema_version") == TASK_SHEET_V3:
                # 结构安全校验（教学语义门禁已移除）：结构非法时保留原版。
                validated_model = TaskSheetContentV3.model_validate(content)
            elif task.task_type == "video_script" and (content or {}).get("schema_version") == "4.0":
                from app.schemas.video_script_v4 import SeedanceVideoScriptContentV4

                validated_model = SeedanceVideoScriptContentV4.model_validate(content)
            else:
                validated_model = TASK_SCHEMAS[task.task_type].model_validate(content)
            # Agentic V4 message runs publish the structurally valid candidate directly.
            # Content-quality rules (required terms/numbers, narration pacing, fact baseline,
            # sentence style, etc.) are advisory only and must not block the teacher's edit.
            # Legacy/non-agentic generation keeps its existing validation behavior.
            if task.task_type == "video_script" and not use_video_script_pipeline:
                if isinstance(validated_model, VideoScriptContent):
                    validated_model = repair_video_script_subtitles(validated_model)
                lesson_artifact = await _latest_artifact(db, course.id, "lesson_plan")
                # 共享项目记忆：教学设计缺失时用蓝图兜底参与引用校验（不阻塞）。
                lesson_raw = (
                    lesson_artifact.content_json
                    if lesson_artifact
                    else make_lesson_plan(blueprint_schema).model_dump()
                )
                video_issues = validate_video_script(
                    blueprint_schema,
                    validated_model.model_dump(), lesson_raw, None,
                )
                blocking = [item for item in video_issues if item["severity"] in {"critical", "major"}]
                if blocking:
                    if run.trigger_type == "initial":
                        logger.warning(
                            "Initial video script failed semantic QA; using blueprint draft",
                            extra={"course_id": course.id, "run_id": run.id},
                        )
                        fallback_lesson = make_lesson_plan(blueprint_schema)
                        fallback_script = make_seedance_video_script(blueprint_schema, fallback_lesson)
                        content = fallback_script.model_dump()
                        validated_model = SeedanceVideoScriptContent.model_validate(content)
                        video_issues = validate_video_script(
                            blueprint_schema, validated_model.model_dump(),
                            fallback_lesson.model_dump(), None,
                        )
                        blocking = [item for item in video_issues if item["severity"] in {"critical", "major"}]
                    if blocking:
                        raise TaskValidationError(f"视频脚本校验未通过：{blocking[0]['description']}")
            if task.task_type == "exercise" and not use_exercise_pipeline:
                # 旧路径（开关关闭）：后置规则门禁 + LLM 复核修复（只修一次）。
                task_sheet_artifact = await _latest_artifact(db, course.id, "task_sheet")
                exercise_issues = validate_exercise(
                    blueprint_schema,
                    validated_model.model_dump(),
                    task_sheet_artifact.content_json if task_sheet_artifact else None,
                )
                blocking = [item for item in exercise_issues if item["severity"] in {"critical", "major"}]
                if blocking:
                    raise TaskValidationError(f"课后练习校验未通过：{blocking[0]['description']}")
                _, review_provider, _ = await _profile_provider(db, course, task)
                validated_model, _ = await review_and_repair_exercise(
                    review_provider,
                    validated_model,
                    task_sheet_artifact.content_json if task_sheet_artifact else None,
                )
                review_data = validated_model.model_dump()
                review_data["review_summary"]["rules_status"] = "passed"
                if visual_notes:
                    review_data["review_summary"]["visual_review_status"] = "degraded"
                    review_data["review_summary"]["needs_teacher_attention"] = True
                    review_data["review_summary"]["notes"].extend(visual_notes)
                else:
                    has_visual = any(
                        stimulus.get("visual")
                        for section in review_data["sections"]
                        for block in section["blocks"]
                        if block["kind"] == "question_group"
                        for stimulus in block["stimuli"]
                    )
                    review_data["review_summary"]["visual_review_status"] = "passed" if has_visual else "not_required"
                validated_model = ExerciseContent.model_validate(review_data)
            validated = validated_model.model_dump()
            if task.task_type == "lesson_plan" and validated.get("schema_version") == "2.0":
                markdown = lesson_plan_to_markdown_v2(validated)
            elif task.task_type == "task_sheet" and validated.get("schema_version") == TASK_SHEET_V3:
                markdown = task_sheet_v3_to_markdown(validated)
            elif task.task_type == "verbatim" and validated.get("schema_version") == "2.0":
                markdown = verbatim_v2_to_markdown(validated)
            else:
                markdown = to_markdown(task.task_type, validated_model)
            if source:
                for lock in locks:
                    if (
                        _locked_value(source.content_json, lock.json_path)
                        != _locked_value(validated, lock.json_path)
                    ):
                        raise RuntimeError(f"模型修改了已锁定内容：{lock.json_path}")
            await _publish_activity(run_id, "validating", 84, "completed")

            version = (await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == course.id,
                Artifact.artifact_type == task.task_type,
            )) or 0) + 1
            await db.commit()

            reply_id = None
            streamed_reply = None
            # PPT / 教学设计 V2 / 任务单 V3 / 视频脚本 V4 / 逐字稿 V2 / 课后练习 V2 的
            # 对话气泡生命周期由 pipeline emitter 拥有（agent_message_*），这里跳过
            # _stream_verified_reply，避免创建第二条 assistant 消息。
            if user_message and revision and provider and (
                task.task_type not in {"ppt", "lesson_plan", "video_script", "verbatim"}
                and not use_task_sheet_pipeline
                and not use_verbatim_pipeline
                and not use_exercise_pipeline
            ):
                current_phase = "replying"
                await _publish_activity(run_id, "replying", 88)
                reply_id, streamed_reply = await _stream_verified_reply(
                    run_id,
                    provider,
                    task,
                    user_message.content,
                    version,
                    revision.assistant_reply,
                )
                await _publish_activity(run_id, "replying", 94, "completed")

            current_phase = "saving"
            await _publish_activity(run_id, "saving", 96)
            await db.rollback()
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run else None
            course = await db.get(CourseProject, run.course_id) if run else None
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == course.id,
                CourseBlueprint.version == course.current_blueprint_version,
            )) if course else None
            if not run or not task or not course or not blueprint:
                raise RuntimeError("保存新版本时任务上下文不存在")

            if use_video_script_pipeline:
                await _apply_pending_video_resolution(db, course, pipeline_runtime)
            if use_verbatim_pipeline and getattr(pipeline_runtime, "pending_course_title", None):
                from app.services.course_metadata_service import apply_course_title_update

                pipeline_runtime.course_title_update = await apply_course_title_update(
                    db, course, pipeline_runtime.pending_course_title,
                )

            artifact = Artifact(
                course_id=course.id,
                artifact_type=task.task_type,
                version=version,
                blueprint_version=blueprint.version,
                content_json=validated,
                content_markdown=markdown,
                status="draft",
                model_name=model_name,
                prompt_version=profile.template_version,
                change_summary=change_summary,
                source_versions_json=source_versions,
                agent_profile_id=profile.id,
                memory_revision_created=run.memory_revision,
            )
            db.add(artifact)
            await db.flush()
            if task.task_type == "ppt":
                from app.services.ppt_artifact_service import record_ppt_revision
                await record_ppt_revision(
                    db, run=run, artifact=artifact, content=validated, source=source,
                    change_summary=change_summary,
                )
            if task.task_type in {"ppt", "exercise"}:
                generated_assets = list(await db.scalars(select(ArtifactAsset).where(
                    ArtifactAsset.generation_run_id == run.id,
                    ArtifactAsset.course_id == course.id,
                    ArtifactAsset.artifact_id.is_(None),
                )))
                for asset in generated_assets:
                    asset.artifact_id = artifact.id
            task.current_artifact_id = artifact.id
            # 共享项目记忆：新 Artifact 在同一事务内索引进项目记忆并推进版本，
            # 避免出现"产物已更新但记忆还没更新"的中间状态。
            from app.services.project_knowledge_service import bump, index_artifact

            await index_artifact(db, artifact, created_by="agent")
            memory_revision = await bump(
                db, course.id, f"{TASK_SPEC_BY_TYPE[task.task_type][1]} 发布 V{version}",
                source_type="artifact", source_id=artifact.id, created_by="agent",
            )
            artifact.memory_revision_created = memory_revision
            # Commit the new Artifact, PPT revision, generated assets and official
            # pointer before the pipeline emits its sole success terminal event.
            # GenerationRun/CourseTask remain non-terminal until that event is done,
            # so clients and test teardown cannot observe completion while the job
            # still owns async DB work.
            if task.task_type == "ppt":
                await db.commit()
                from app.services.ppt_pipeline_service import complete_ppt_pipeline_after_publish
                await complete_ppt_pipeline_after_publish(pipeline_runtime, artifact.id)
            if task.task_type == "lesson_plan" and use_lesson_plan_pipeline:
                await db.commit()
                from app.services.lesson_plan_pipeline_service import complete_lesson_plan_pipeline_after_publish
                await complete_lesson_plan_pipeline_after_publish(pipeline_runtime, artifact.id)
            if task.task_type == "task_sheet" and use_task_sheet_pipeline:
                await db.commit()
                from app.services.task_sheet_pipeline_service import complete_task_sheet_pipeline_after_publish
                await complete_task_sheet_pipeline_after_publish(pipeline_runtime, artifact.id)
            if task.task_type == "video_script" and use_video_script_pipeline:
                await db.commit()
                from app.services.video_script_pipeline_service import complete_video_script_pipeline_after_publish
                await complete_video_script_pipeline_after_publish(pipeline_runtime, artifact.id)
            if task.task_type == "verbatim" and use_verbatim_pipeline:
                await db.commit()
                from app.services.verbatim_pipeline_service import complete_verbatim_pipeline_after_publish
                await complete_verbatim_pipeline_after_publish(pipeline_runtime, artifact.id)
            if task.task_type == "exercise" and use_exercise_pipeline:
                await db.commit()
                from app.services.exercise_pipeline_service import complete_exercise_pipeline_after_publish
                await complete_exercise_pipeline_after_publish(pipeline_runtime, artifact.id)
            final_status = "review" if task.current_agent_profile_id == profile.id else "stale"
            task.status = final_status
            task.progress = 100
            task.active_run_id = None
            task.error_json = None
            task.completed_at = utcnow()
            run.status = "completed"
            run.progress = 100
            run.finished_at = utcnow()

            # PPT / 教学设计 V2 / 任务单 V3 / 视频脚本 V4 / 逐字稿 V2 / 课后练习 V2：
            # assistant 消息已由 pipeline emitter 完成；跳过 reply 处理（reply_id 为空，若不跳过会 raise）。
            if user_message and revision and (
                task.task_type not in {"ppt", "lesson_plan", "video_script", "verbatim"}
                and not use_task_sheet_pipeline
                and not use_verbatim_pipeline
                and not use_exercise_pipeline
            ):
                stored_user_message = await db.get(AgentMessage, user_message.id)
                if stored_user_message:
                    stored_user_message.status = "completed"
                reply = await db.get(AgentMessage, reply_id) if reply_id else None
                if not reply:
                    raise RuntimeError("流式回复记录不存在")
                reply.content = streamed_reply or revision.assistant_reply
                reply.status = "completed"
                reply.artifact_id = artifact.id
                await _emit(db, run, "agent_message_completed", task, message={
                    "id": reply.id,
                    "role": "assistant",
                    "content": reply.content,
                    "artifact_id": artifact.id,
                    "run_id": run.id,
                    "status": "completed",
                })

            stale_tasks = await _mark_dependents_stale(db, task, version)
            for stale_task in stale_tasks:
                await _emit(
                    db,
                    run,
                    "task_dependency_stale",
                    stale_task,
                    status="stale",
                    progress=stale_task.progress,
                    stale_dependencies=[task.task_type],
                )
            await _refresh_quality(db, course, blueprint)
            await _refresh_course_status(db, course)
            await _emit(
                db,
                run,
                "task_activity_updated",
                task,
                status=final_status,
                progress=100,
                phase="completed",
                phase_label=PHASE_LABELS["completed"],
                detail=PHASE_DETAILS["completed"],
                phase_status="completed",
                elapsed_ms=0,
            )
            await _emit(
                db,
                run,
                "artifact_version_created",
                task,
                status=final_status,
                progress=100,
                artifact=artifact_payload(artifact),
            )
            # 共享项目记忆标准化事件：新前端消费，旧前端忽略。
            await _emit(
                db,
                run,
                "artifact.published",
                task,
                status=final_status,
                progress=100,
                artifact=artifact_payload(artifact),
                memory_revision=memory_revision,
            )
            await _emit(
                db,
                run,
                "project_memory.updated",
                task,
                status=final_status,
                memory_revision=memory_revision,
                change_reason=f"{TASK_SPEC_BY_TYPE[task.task_type][1]} 发布 V{version}",
            )
            await _emit(db, run, "task_status_changed", task, status=final_status, progress=100)
            await db.commit()
        await schedule_ready_tasks(course.id)
    except asyncio.CancelledError:
        # pause API 会抢占当前 LLM/Tool await。若暂停信号存在，这是可恢复暂停，不是取消任务。
        from app.services.ppt_pipeline_service import PAUSE_EVENTS
        pause_event = PAUSE_EVENTS.get(run_id)
        if pause_event is not None and pause_event.is_set():
            async with SessionLocal() as db:
                run = await db.get(GenerationRun, run_id)
                task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
                pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
                if run:
                    run.status = "paused"
                if pipeline:
                    pipeline.status = "paused"
                    pipeline.checkpoint_json = {
                        **(pipeline.checkpoint_json or {}),
                        "step_index": pipeline.current_step_index,
                        "paused_agent": pipeline.current_agent or current_phase,
                        "preempted": True,
                    }
                if task and run:
                    task.status = "paused"
                    await _emit(db, run, "task_paused", task, status="paused", reason="用户暂停")
                    await _emit(db, run, "task_status_changed", task, status="paused", progress=task.progress)
                await db.commit()
            return
        await _mark_streaming_reply_failed(run_id, "任务已取消，流式回复未完成。")
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
            if run:
                run.status = "cancelled"
                run.finished_at = utcnow()
            if pipeline:
                pipeline.status = "cancelled"
            if task:
                task.status = "cancelled"
                task.active_run_id = None
                await _emit(
                    db,
                    run,
                    "task_activity_updated",
                    task,
                    status="cancelled",
                    progress=task.progress,
                    phase=current_phase,
                    phase_label=PHASE_LABELS[current_phase],
                    detail="任务已由教师取消。",
                    phase_status="failed",
                    elapsed_ms=0,
                )
                await _emit(db, run, "task_status_changed", task, status="cancelled", progress=task.progress)
            await db.commit()
    except PipelinePaused:
        # 流水线在 Agent 边界暂停：持久化 paused，保留 active_run_id 供恢复
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if not run or not task:
                return
            run.status = "paused"
            task.status = "paused"
            await _emit(db, run, "task_paused", task, status="paused", reason="用户暂停")
            await _emit(db, run, "task_status_changed", task, status="paused", progress=task.progress)
            await db.commit()
    except Exception as exc:
        logger.exception("Course task run failed", extra={"run_id": run_id})
        await _mark_streaming_reply_failed(run_id, "文件生成或保存失败，本次回复未完成。")
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            course = await db.get(CourseProject, run.course_id) if run else None
            pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
            if not run or not task:
                return
            error, internal_detail = _task_failure_payload(exc)
            code = str(error["code"])
            message = str(error["message"])
            run.status = "failed"
            run.error_json = error
            run.finished_at = utcnow()
            task.status = "failed"
            task.active_run_id = None
            task.error_json = error
            if pipeline:
                pipeline.status = "failed"
                pipeline.error_json = {**error, "internal_detail": internal_detail}
                from app.models.entities import PPTHumanRequest
                pending_human_requests = list(await db.scalars(select(PPTHumanRequest).where(
                    PPTHumanRequest.pipeline_run_id == pipeline.id,
                    PPTHumanRequest.status == "pending",
                )))
                for human_request in pending_human_requests:
                    human_request.status = "cancelled"
                    human_request.response_json = {"reason": "run_failed", "error_code": code}
                    human_request.resolved_at = utcnow()
            message_row = await db.scalar(select(AgentMessage).where(
                AgentMessage.run_id == run.id,
                AgentMessage.role == "user",
            ))
            if message_row:
                message_row.status = "failed"
            if course:
                await _refresh_course_status(db, course)
            await _emit(
                db,
                run,
                "task_activity_updated",
                task,
                status="failed",
                progress=task.progress,
                phase=current_phase,
                phase_label=PHASE_LABELS[current_phase],
                detail=message,
                phase_status="failed",
                elapsed_ms=0,
            )
            await _emit(db, run, "task_failed", task, status="failed", progress=task.progress, error=error)
            await db.commit()
            if pipeline:
                from app.agent.events import PipelineEventEmitter
                failure_emitter = await PipelineEventEmitter.for_run(run, pipeline, task_type=task.task_type)
                await failure_emitter.pipeline_failed(error=message)
                await failure_emitter.emit_domain("run.failed", message=message, payload={"error": error})
                artifact_label = {
                    "lesson_plan": "教学设计",
                    "ppt": "PPT课件",
                    "task_sheet": "学习任务单",
                    "video_script": "视频脚本",
                    "verbatim": "教师逐字稿",
                    "exercise": "课后练习",
                }.get(task.task_type, "任务文件")
                await failure_emitter.emit_domain(
                    "artifact.draft.cleared", message=f"本轮草稿已清除，继续显示原正式{artifact_label}",
                    payload={"run_id": run.id, "reason": code},
                )
    finally:
        task_jobs.pop(run_id, None)


async def resume_incomplete_task_runs():
    run_ids = []
    async with SessionLocal() as db:
        runs = list(await db.scalars(select(GenerationRun).where(
            GenerationRun.run_type == "task",
            GenerationRun.status.in_(["queued", "running", "pausing"]),
        )))
        for run in runs:
            pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run.id))
            if run.status == "pausing":
                run.status = "paused"
                if pipeline:
                    pipeline.status = "paused"
                if run.course_task_id:
                    task = await db.get(CourseTask, run.course_task_id)
                    if task:
                        task.status = "paused"
                        task.active_run_id = run.id
                continue
            run.status = "queued"
            if pipeline:
                pipeline.status = "queued"
            if run.course_task_id:
                task = await db.get(CourseTask, run.course_task_id)
                if task:
                    task.status = "queued"
                    task.active_run_id = run.id
            run_ids.append(run.id)
        await db.commit()
    for run_id in run_ids:
        start_task_run(run_id)


def intent_summary(course: CourseProject, requirement: CourseRequirement | None) -> dict:
    settings = course.settings_json or {}
    assumptions = requirement.assumptions_json if requirement else []
    return {
        "headline": f"为{course.grade_level or course.audience}设计一节围绕“{course.title}”的{course.subject}微课",
        "title": course.title,
        "subject": course.subject,
        "grade_level": course.grade_level,
        "audience": course.audience,
        "duration_minutes": course.duration_minutes,
        "scenario": course.scenario,
        "course_task": settings.get("course_task", ""),
        "teaching_objectives": settings.get("teaching_objectives", ""),
        "key_points": settings.get("key_points", ""),
        "difficulty_points": settings.get("difficulty_points", ""),
        "teaching_method": settings.get("teaching_method", ""),
        "style_requirements": settings.get("style_requirements", ""),
        "assumptions": assumptions,
        "deliverables": [spec[1] for spec in TASK_SPECS],
    }
