"""Artifact 工具：读取蓝图、上游产物、当前 PPT、知识库（只读，供 Agent 决策）。"""
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseBlueprint, CourseProject


class GetBlueprintInput(BaseModel):
    pass


async def _get_blueprint(tc: ToolContext, _: GetBlueprintInput) -> ToolResult:
    if tc.ctx.blueprint is not None:
        data = tc.ctx.blueprint if isinstance(tc.ctx.blueprint, dict) else tc.ctx.blueprint.model_dump()
        return ToolResult(ok=True, output={"blueprint": data, "source": "context"})
    async with SessionLocal() as db:
        course = await db.get(CourseProject, tc.course.id)
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course.id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        if not blueprint:
            return ToolResult(ok=False, error="课程蓝图不存在")
        return ToolResult(ok=True, output={"blueprint": blueprint.content_json, "version": blueprint.version})


class GetUpstreamArtifactsInput(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["lesson_plan"])


async def _get_upstream_artifacts(tc: ToolContext, payload: GetUpstreamArtifactsInput) -> ToolResult:
    if tc.ctx.upstream:
        matched = {kind: value for kind, value in tc.ctx.upstream.items() if kind in payload.kinds}
        if matched:
            return ToolResult(ok=True, output={"artifacts": matched, "source": "context"})
    async with SessionLocal() as db:
        result: dict[str, Any] = {}
        for kind in payload.kinds:
            row = await db.scalar(select(Artifact).where(
                Artifact.course_id == tc.course.id, Artifact.artifact_type == kind,
            ).order_by(Artifact.version.desc()))
            if row:
                result[kind] = row.content_json
        if not result:
            return ToolResult(ok=False, error=f"上游产物不存在：{payload.kinds}")
        return ToolResult(ok=True, output={"artifacts": result})


class GetPptSourceInput(BaseModel):
    pass


async def _get_ppt_source(tc: ToolContext, _: GetPptSourceInput) -> ToolResult:
    source = tc.ctx.source_artifact
    if source is None:
        return ToolResult(ok=False, error="当前没有 PPT 源文件（首次生成）")
    content = getattr(source, "content_json", source)
    return ToolResult(ok=True, output={"content": content})


class GetKnowledgeBaseInput(BaseModel):
    pass


async def _get_knowledge_base(tc: ToolContext, _: GetKnowledgeBaseInput) -> ToolResult:
    from app.services.ppt_knowledge_service import load_ppt_design_knowledge
    return ToolResult(ok=True, output={"knowledge": load_ppt_design_knowledge()})


def register_artifact_tools():
    register_tool(Tool("get_blueprint", "读取已批准课程蓝图（结构化内容）", GetBlueprintInput, _get_blueprint))
    register_tool(Tool("get_upstream_artifacts", "读取上游 Agent 产物（如 lesson_plan）", GetUpstreamArtifactsInput, _get_upstream_artifacts))
    register_tool(Tool("get_ppt_source", "读取当前 PPT 源内容（修订时）", GetPptSourceInput, _get_ppt_source))
    register_tool(Tool("get_knowledge_base", "读取 PPT 设计知识库（密度/版式/反模式）", GetKnowledgeBaseInput, _get_knowledge_base))


register_artifact_tools()
