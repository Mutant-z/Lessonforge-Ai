import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import artifact_assets, artifacts, auth, blueprints, courses, exports, intakes, materials, ppt_pipeline, ppt_templates, projects, quality, settings
from app.core.config import get_settings
from app.core.database import SessionLocal, create_schema
from app.services.project_planning_service import planning_jobs
from app.services.intake_service import intake_tasks
from app.services.course_task_service import resume_incomplete_task_runs, task_jobs
from app.services.agent_initialization_service import initialization_jobs, resume_incomplete_initialization_runs
from app.services.exercise_visual_service import cleanup_orphan_artifact_assets


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings().prepare_storage()
    await create_schema()
    async with SessionLocal() as db:
        await cleanup_orphan_artifact_assets(db)
    await resume_incomplete_initialization_runs()
    await resume_incomplete_task_runs()
    try:
        yield
    finally:
        pending = list(planning_jobs.values()) + list(intake_tasks.values()) + list(task_jobs.values()) + list(initialization_jobs.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "lessonforge-api"}


for module in (auth, courses, materials, intakes, blueprints, artifacts, artifact_assets, ppt_templates, ppt_pipeline, projects, quality, exports, settings):
    app.include_router(module.router, prefix="/api/v1")
