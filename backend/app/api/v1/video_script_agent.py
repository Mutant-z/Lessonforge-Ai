"""视频脚本 Agent API：runs / messages。

- POST /courses/{course_id}/tasks/video_script/runs —— 创建运行（initial 或带指令的 message）
- POST /courses/{course_id}/tasks/video_script/messages —— 教师修改指令（携带章节/分镜作用域与 mode）

运行详情 / SSE 事件流 / 人工确认复用通用 /agent-runs/{run_id} 等端点（见 lesson_plan_agent，
已按运行所属任务通用化，不限任务类型）。流水线详情 / pause / resume 复用已 task_type
参数化的 /tasks/{task_type}/pipeline 等端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.v1.projects import _owned_task, _validated_chat_attachment_metadata
from app.core.database import get_db
from app.models.entities import AgentMessage, User
from app.services.course_task_service import create_task_run, start_task_run

video_script_router = APIRouter(tags=["video-script-agent"])

TASK_TYPE = "video_script"


class VideoScriptMessageRequest(BaseModel):
    content: str = Field(default="", max_length=8000)
    #: 兼容旧客户端操作（initial / retry / sync_dependencies / sync_context）。
    action: str = Field(default="message", max_length=30)
    selected_section_ids: list[str] = Field(default_factory=list, max_length=50)
    selected_scene_ids: list[str] = Field(default_factory=list, max_length=100)
    active_section_id: str | None = None
    active_scene_id: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|content|structure|narration|visual|continuity|timing|qa)$")
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


@video_script_router.post("/courses/{course_id}/tasks/video_script/runs", status_code=202)
async def create_video_script_run(
    course_id: str,
    payload: VideoScriptMessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _owned_task(course_id, TASK_TYPE, user, db)
    # 兼容旧客户端操作：initial / retry / sync_dependencies / sync_context 委托通用分发。
    if payload.action != "message":
        from app.api.v1.projects import dispatch_task_run_action

        return await dispatch_task_run_action(db, task, payload.action)
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, "修改指令不能为空")
    attachment_meta = await _validated_chat_attachment_metadata(db, user, course_id, payload.attachment_ids)
    message = AgentMessage(
        course_id=course_id, task_id=task.id, module_type=TASK_TYPE,
        role="user", content=content, status="pending",
    )
    if any((payload.selected_section_ids, payload.selected_scene_ids, payload.active_section_id, payload.active_scene_id, payload.mode != "auto")) or attachment_meta:
        message.metadata_json = {
            "selected_section_ids": list(payload.selected_section_ids),
            "selected_scene_ids": list(payload.selected_scene_ids),
            "active_section_id": payload.active_section_id,
            "active_scene_id": payload.active_scene_id,
            "mode": payload.mode,
            **attachment_meta,
        }
    db.add(message)
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"message_id": message.id, "run_id": run.id, "task_id": task.id, "status": "queued"}


@video_script_router.post("/courses/{course_id}/tasks/video_script/messages", status_code=202)
async def send_video_script_message(
    course_id: str,
    payload: VideoScriptMessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_video_script_run(course_id, payload, user, db)
