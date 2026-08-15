"""共享项目记忆 API：查看记忆版本、条目、检索与任务上下文清单。

只读接口：用户可以通过记忆面板查看各来源的摘要与版本，但不能通过记忆面板
直接越权修改其他 Agent 产物（修改仍走各自任务工作区）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import get_db
from app.models.entities import CourseTask, User
from app.services.course_task_service import (
    CONTENT_TASK_TYPES,
    TASK_SPEC_BY_TYPE,
    ensure_course_tasks,
    task_payload,
)
from app.services.project_knowledge_service import (
    current_revision,
    ensure_initialized,
    get_item,
    list_items,
    search_items,
    serialize_item,
)

router = APIRouter(tags=["项目记忆"])


@router.get("/courses/{course_id}/memory")
async def get_project_memory(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    await ensure_course_tasks(db, course_id)
    await ensure_initialized(db, course_id)
    revision = await current_revision(db, course_id)
    items = await list_items(db, course_id, limit=200)
    await db.commit()
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item.source_type, []).append(serialize_item(item))
    return {
        "revision": revision,
        "items": grouped,
        "item_count": len(items),
    }


@router.get("/courses/{course_id}/memory/items/{item_id}")
async def get_project_memory_item(course_id: str, item_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    item = await get_item(db, course_id, item_id)
    if not item:
        raise HTTPException(404, "项目记忆条目不存在")
    return serialize_item(item)


@router.get("/courses/{course_id}/memory/search")
async def search_project_memory(
    course_id: str,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_course(course_id, user, db)
    if not q.strip():
        return {"query": q, "items": []}
    items = await search_items(db, course_id, q, limit=limit)
    return {"query": q, "items": [serialize_item(item) for item in items]}


@router.get("/courses/{course_id}/memory/context")
async def get_project_memory_context(
    course_id: str,
    task_type: str = Query(default="", max_length=60),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """某个 Agent 的上下文清单：记忆版本、可读取参考产物、缺失可选来源。"""
    await owned_course(course_id, user, db)
    await ensure_course_tasks(db, course_id)
    if task_type:
        if task_type not in TASK_SPEC_BY_TYPE:
            raise HTTPException(404, "项目任务不存在")
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == task_type,
        ))
    else:
        task = None
    if task is None or task.task_type not in CONTENT_TASK_TYPES:
        return {
            "memory_revision": await current_revision(db, course_id),
            "task_type": task_type,
            "available_sources": {},
            "missing_optional_sources": [],
            "last_context_revision": task.last_context_revision if task else 0,
        }
    payload = await task_payload(db, task)
    return {
        "memory_revision": await current_revision(db, course_id),
        "task_type": task_type,
        "available_sources": payload["available_sources"],
        "missing_optional_sources": payload["missing_optional_sources"],
        "optional_reference_types": payload["optional_reference_types"],
        "last_context_revision": task.last_context_revision,
        "current_artifact_version": (payload.get("current_artifact") or {}).get("version"),
    }
