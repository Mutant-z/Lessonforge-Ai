import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import artifact_assets, artifacts, auth, blueprints, courses, exports, intakes, lesson_plan_agent, materials, memory, ppt_agent, ppt_pipeline, ppt_templates, projects, quality, settings, task_sheet_agent, verbatim_agent, video_generation, video_script_agent
from app.core.config import get_settings
from app.core.database import SessionLocal, create_schema
from app.services.project_planning_service import planning_jobs
from app.services.intake_service import intake_tasks
from app.services.course_task_service import resume_incomplete_task_runs, task_jobs
from app.services.agent_initialization_service import initialization_jobs, resume_incomplete_initialization_runs
from app.services.exercise_visual_service import cleanup_orphan_artifact_assets


@asynccontextmanager
async def lifespan(application: FastAPI):
    get_settings().prepare_storage()
    await create_schema()
    async with SessionLocal() as db:
        from app.services.video_generation_settings_service import reconcile_video_generation_preferences
        application.state.video_generation_preference_reconciliation = (
            await reconcile_video_generation_preferences(db)
        )
        await cleanup_orphan_artifact_assets(db)
        from app.services.seedance_provider_service import probe_configured_seedance_models
        from app.services.gemini_interactions_video_service import probe_configured_gemini_video_models
        application.state.seedance_capability_report = await probe_configured_seedance_models(db)
        application.state.gemini_video_capability_report = await probe_configured_gemini_video_models(db)
    await resume_incomplete_initialization_runs()
    await resume_incomplete_task_runs()
    try:
        yield
    finally:
        pending = list(dict.fromkeys(
            list(planning_jobs.values()) + list(intake_tasks.values())
            + list(task_jobs.values()) + list(initialization_jobs.values())
        ))
        for task in pending:
            task.cancel()
        if pending:
            # Provider calls may delay cancellation. Shutdown must remain bounded so
            # restart/测试 teardown cannot hang behind an abandoned generation job.
            done, still_pending = await asyncio.wait(pending, timeout=3)
            for task in done:
                if not task.cancelled():
                    task.exception()
            for task in still_pending:
                task.cancel()


app = FastAPI(title="LessonForge AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_id(request: Request, call_next):
    value = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse(status_code=500, content={"detail": "服务器处理请求失败", "request_id": value})
    response.headers["X-Request-ID"] = value
    content_type = response.headers.get("content-type", "")
    if request.method == "GET" and request.url.path.startswith("/api/v1/") and "application/json" in content_type:
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/health")
async def health():
    probes = getattr(app.state, "seedance_capability_report", [])
    gemini_probes = getattr(app.state, "gemini_video_capability_report", [])
    return {
        "status": "ok",
        "service": "lessonforge-api",
        "seedance": {
            "configured": len(probes),
            "ready": sum(1 for item in probes if item.get("status") == "ready"),
            "blocked": sum(1 for item in probes if item.get("status") == "blocked"),
        },
        "gemini_interactions_video": {
            "enabled": get_settings().gemini_interactions_video_enabled,
            "configured": len(gemini_probes),
            "ready": sum(1 for item in gemini_probes if item.get("status") == "ready"),
            "blocked": sum(1 for item in gemini_probes if item.get("status") == "blocked"),
        },
    }


for module in (auth, courses, materials, intakes, blueprints, artifacts, artifact_assets, ppt_templates, ppt_pipeline, ppt_agent, video_generation, quality, exports, settings, memory):
    app.include_router(module.router, prefix="/api/v1")
# Agent 专用 /tasks/{task_type}/runs|messages 必须先于 projects 泛化路由注册，
# 否则会被 projects.run_task / send_task_message 抢先匹配（run_task 的 action
# 默认 retry，会把对话请求误判为 409）。
app.include_router(lesson_plan_agent.lesson_plan_router, prefix="/api/v1")
app.include_router(task_sheet_agent.router, prefix="/api/v1")
app.include_router(video_script_agent.video_script_router, prefix="/api/v1")
app.include_router(verbatim_agent.verbatim_router, prefix="/api/v1")
app.include_router(lesson_plan_agent.router, prefix="/api/v1")
# projects 泛化路由最后注册，让更具体的 agent 路由优先。
app.include_router(projects.router, prefix="/api/v1")
