"""PPT 模板工具：读取模板目录、解析模板设计系统（调色板/字体/装饰几何）。"""
from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import design_system_for
from app.services.ppt_template_service import get_ppt_template, list_ppt_templates, resolve_ppt_template
from app.services.ppt_template_analysis_service import analyze_template


class GetTemplateCatalogInput(BaseModel):
    pass


async def _get_template_catalog(tc: ToolContext, _: GetTemplateCatalogInput) -> ToolResult:
    return ToolResult(ok=True, output={"templates": list_ppt_templates()})


class GetTemplateDesignInput(BaseModel):
    template_id: str | None = Field(default=None, description="模板 id，缺省用当前主题")


def _effective_template_id(tc: ToolContext, requested: str | None = None) -> str | None:
    """模板 ID 的唯一解析入口，兼容 catalog design 与 PPTX analysis profile。"""
    context_template = tc.ctx.template or {}
    return (
        requested
        or getattr(tc.runtime, "preferred_template", None)
        or context_template.get("id")
        or context_template.get("template_id")
        or ((tc.builder.template or {}).get("id") if tc.builder is not None else None)
    )


async def _get_template_design(tc: ToolContext, payload: GetTemplateDesignInput) -> ToolResult:
    template_id = _effective_template_id(tc, payload.template_id)
    template = resolve_ppt_template(template_id)
    design = design_system_for(template)
    if tc.builder is not None:
        # 同步当前 builder 设计系统（编辑工具按模板设计语言工作）
        tc.builder.apply_template(template["id"])
    tc.ctx.template = {**(tc.ctx.template or {}), **design, "template_id": template["id"]}
    return ToolResult(ok=True, output={"template": template, "design_system": design})


async def _inspect_template(tc: ToolContext, payload: GetTemplateDesignInput) -> ToolResult:
    template_id = _effective_template_id(tc, payload.template_id)
    digest, profile = analyze_template(template_id)
    try:
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.entities import PPTTemplateProfile
        async with SessionLocal() as db:
            row = await db.scalar(select(PPTTemplateProfile).where(
                PPTTemplateProfile.template_id == profile["template_id"],
                PPTTemplateProfile.template_hash == digest,
            ))
            if row is None:
                row = PPTTemplateProfile(
                    template_id=profile["template_id"], template_hash=digest,
                    catalog_version=profile["catalog_version"], profile_json=profile,
                )
                db.add(row)
                await db.commit()
    except Exception:
        # Template inspection remains usable before migrations are applied.
        pass
    resolved = resolve_ppt_template(profile.get("template_id") or template_id)
    tc.ctx.template = {
        **design_system_for(resolved), **profile,
        "id": resolved["id"], "template_id": resolved["id"],
    }
    return ToolResult(ok=True, output={"template_profile": profile, "cache_key": digest})


class SelectTemplateInput(BaseModel):
    template_id: str


async def _select_template(tc: ToolContext, payload: SelectTemplateInput) -> ToolResult:
    template = get_ppt_template(payload.template_id)
    if template is None:
        return ToolResult(ok=False, error=f"模板不存在：{payload.template_id}")
    if tc.builder is not None:
        tc.builder.apply_template(payload.template_id)
    tc.ctx.template = design_system_for(template)
    return ToolResult(ok=True, output={"template": template, "selected": template["id"]})


def register_template_tools():
    register_tool(Tool("get_template_catalog", "读取 PPT 模板目录（6 套设计系统元数据）", GetTemplateCatalogInput, _get_template_catalog))
    register_tool(Tool("get_template_design", "解析模板设计系统（调色板/字体/装饰几何/安全边距）", GetTemplateDesignInput, _get_template_design))
    register_tool(Tool("inspect_template", "读取真实 PPTX 的 Master、Layout、Shape、字体和示例页", GetTemplateDesignInput, _inspect_template, timeout_seconds=30, idempotent=True))
    register_tool(Tool("select_template", "选择模板并应用到当前 builder", SelectTemplateInput, _select_template))


register_template_tools()
