"""共享项目记忆读取工具（只读，供 Agent 工作过程中按需读取其他 Agent 内容）。

这些工具不控制任何 Agent 的启动顺序：六类内容 Agent 全部并行启动，每次运行
读取一个记忆快照（build_project_knowledge_context 注入的 sibling_artifacts /
available_sources），工作中可再通过本模块按需读取其他 Agent 的最新可用内容。
工具返回内容附带来源 Agent / 类型 / 版本 / 状态 / 是否快照内 / 引用路径 /
信任级别，便于 Agent 区分"教师明确要求、系统规则、上传材料、Agent 生成内容"。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseProject, ProjectMemoryItem
from app.services.project_knowledge_service import serialize_item

SOURCE_TYPE_LITERAL = Literal[
    "requirement", "blueprint", "material", "artifact", "decision", "qa", "dialogue"
]


async def _record_source_read(tc: ToolContext, tool_name: str, detail: dict[str, Any]) -> None:
    """尽力记录一次共享记忆读取（失败不阻断工具结果）。"""
    try:
        emitter = getattr(tc, "emitter", None)
        if emitter is not None and hasattr(emitter, "emit_domain"):
            await emitter.emit_domain(
                "memory.source_read",
                message=f"{tool_name} 读取了项目记忆",
                payload={"tool": tool_name, **detail},
            )
            return
        from sqlalchemy import text

        async with SessionLocal() as db:
            course_id = tc.course.id if tc.course is not None else ""
            run_id = getattr(tc, "generation_run_id", "") or ""
            if not course_id or not run_id:
                return
            await db.execute(text(
                "INSERT INTO generation_events (run_id, event_type, data_json, created_at) "
                "VALUES (:run_id, 'memory.source_read', :data, datetime('now'))"
            ), {
                "run_id": run_id,
                "data": str({
                    "course_id": course_id,
                    "run_id": run_id,
                    "tool": tool_name,
                    "detail": detail,
                }),
            })
            await db.commit()
    except Exception:  # pragma: no cover - 读取日志失败不影响工具
        pass


class ListProjectMemoryInput(BaseModel):
    source_type: str | None = None
    limit: int = Field(default=100, ge=1, le=200)


async def _list_project_memory(tc: ToolContext, payload: ListProjectMemoryInput) -> ToolResult:
    async with SessionLocal() as db:
        query = select(ProjectMemoryItem).where(
            ProjectMemoryItem.course_id == tc.course.id,
        )
        if payload.source_type:
            query = query.where(ProjectMemoryItem.source_type == payload.source_type)
        items = list(await db.scalars(query.order_by(ProjectMemoryItem.updated_at.desc()).limit(payload.limit)))
        await _record_source_read(tc, "list_project_memory", {"source_type": payload.source_type or "all", "count": len(items)})
        return ToolResult(ok=True, output={
            "memory_items": [serialize_item(item) for item in items],
        })


class SearchProjectMemoryInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=30, ge=1, le=100)


async def _search_project_memory(tc: ToolContext, payload: SearchProjectMemoryInput) -> ToolResult:
    from app.services.project_knowledge_service import search_items

    async with SessionLocal() as db:
        items = await search_items(db, tc.course.id, payload.query, limit=payload.limit)
        await _record_source_read(tc, "search_project_memory", {"query": payload.query[:60], "count": len(items)})
        return ToolResult(ok=True, output={
            "query": payload.query,
            "memory_items": [serialize_item(item) for item in items],
        })


class ReadProjectMemoryItemInput(BaseModel):
    item_id: str = Field(min_length=1, max_length=120)


async def _read_project_memory_item(tc: ToolContext, payload: ReadProjectMemoryItemInput) -> ToolResult:
    from app.services.project_knowledge_service import get_item

    async with SessionLocal() as db:
        item = await get_item(db, tc.course.id, payload.item_id)
        if item is None:
            return ToolResult(ok=False, error=f"项目记忆条目不存在：{payload.item_id}")
        await _record_source_read(tc, "read_project_memory_item", {"item_id": item.id, "source_type": item.source_type})
        return ToolResult(ok=True, output={"memory_item": serialize_item(item)})


class ReadArtifactVersionInput(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=60)
    version: int | None = None


def _artifact_trust(artifact: Artifact) -> str:
    if artifact.artifact_type in {"quality_report", "citation_report"}:
        return "system_generated"
    return "agent_generated"


def _artifact_payload(artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_type": artifact.artifact_type,
        "version": artifact.version,
        "status": artifact.status,
        "blueprint_version": artifact.blueprint_version,
        "change_summary": artifact.change_summary,
        "memory_revision_created": artifact.memory_revision_created or 0,
        "source_versions": artifact.source_versions_json or {},
        "content": artifact.content_json or {},
    }


async def _read_artifact_version(tc: ToolContext, payload: ReadArtifactVersionInput) -> ToolResult:
    async with SessionLocal() as db:
        query = select(Artifact).where(
            Artifact.course_id == tc.course.id,
            Artifact.artifact_type == payload.artifact_type,
        )
        if payload.version is not None:
            query = query.where(Artifact.version == payload.version)
        else:
            query = query.order_by(Artifact.version.desc())
        artifact = await db.scalar(query.limit(1))
        if artifact is None:
            return ToolResult(ok=False, error=f"项目中不存在 {payload.artifact_type} 的 Artifact")
        snapshot_available = bool(
            tc.ctx is not None
            and tc.ctx.upstream.get(payload.artifact_type) is not None
        )
        await _record_source_read(tc, "read_artifact_version", {
            "artifact_type": payload.artifact_type, "version": artifact.version,
        })
        return ToolResult(ok=True, output={
            **_artifact_payload(artifact),
            "trust_level": _artifact_trust(artifact),
            "in_context_snapshot": snapshot_available,
            "content_ref": f"artifact:{artifact.id}",
        })


class GetLatestProjectArtifactInput(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=60)


async def _get_latest_project_artifact(tc: ToolContext, payload: GetLatestProjectArtifactInput) -> ToolResult:
    return await _read_artifact_version(tc, ReadArtifactVersionInput(artifact_type=payload.artifact_type))


def register_memory_tools():
    register_tool(Tool(
        "list_project_memory",
        "列出共享项目记忆中的条目（需求/蓝图/材料/Artifact/决策/QA，可按类型过滤）",
        ListProjectMemoryInput, _list_project_memory,
    ))
    register_tool(Tool(
        "search_project_memory",
        "在共享项目记忆中按关键词检索条目",
        SearchProjectMemoryInput, _search_project_memory,
    ))
    register_tool(Tool(
        "read_project_memory_item",
        "读取共享项目记忆中的单条索引（含摘要与引用路径）",
        ReadProjectMemoryItemInput, _read_project_memory_item,
    ))
    register_tool(Tool(
        "read_artifact_version",
        "按类型与版本读取项目中任意 Agent 的 Artifact 内容（可指定版本，默认最新）",
        ReadArtifactVersionInput, _read_artifact_version,
    ))
    register_tool(Tool(
        "get_latest_project_artifact",
        "读取项目中某类型 Agent 的最新 Artifact 内容（如 video_script/lesson_plan）",
        GetLatestProjectArtifactInput, _get_latest_project_artifact,
    ))


register_memory_tools()
