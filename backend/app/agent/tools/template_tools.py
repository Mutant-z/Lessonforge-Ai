"""PPT 模板工具：读取模板目录、解析模板设计系统（调色板/字体/装饰几何）。"""
from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import design_system_for
from app.services.ppt_template_service import get_ppt_template, list_ppt_templates, resolve_ppt_template


class GetTemplateCatalogInput(BaseModel):
    pass


async def _get_template_catalog(tc: ToolContext, _: GetTemplateCatalogInput) -> ToolResult:
    return ToolResult(ok=True, output={"templates": list_ppt_templates()})


class GetTemplateDesignInput(BaseModel):
    template_id: str | None = Field(default=None, description="模板 id，缺省用当前主题")


async def _get_template_design(tc: ToolContext, payload: GetTemplateDesignInput) -> ToolResult:
    template_id = payload.template_id or (tc.ctx.template or {}).get("id")
    template = resolve_ppt_template(template_id)
    design = design_system_for(template)
    if tc.builder is not None:
        # 同步当前 builder 设计系统（编辑工具按模板设计语言工作）
        tc.builder.apply_template(template["id"])
    return ToolResult(ok=True, output={"template": template, "design_system": design})


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
    register_tool(Tool("select_template", "选择模板并应用到当前 builder", SelectTemplateInput, _select_template))


register_template_tools()
