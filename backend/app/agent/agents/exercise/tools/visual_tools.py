"""课后练习工具集：视觉材料工具。

- exercise_render_diagram：LLM 提供确定性图示规格（diagram_type/diagram_spec），
  由确定性渲染器（render_deterministic_svg）落图并绑定资产（approved）。
- exercise_generate_image：LLM 提供生成式图片 prompt，调用图片模型生成 + 视觉
  模型复核；通过则 approved，失败则标记 degraded（降级决策由视觉角色 LLM 决定）。
- exercise_degrade_visual：把视觉材料替换为 LLM 提供的等价文字替代材料。

存储与资产绑定参照 exercise_visual_service.process_exercise_visuals 的既有模式
（sha256 去重、storage/generated/{course_id}/...）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.agents.exercise.tools._common import _builder, _lock_guard
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentChatSession, ArtifactAsset, ModelConfig


async def _session_configs(tc: ToolContext):
    """返回 (image_config, vision_config, note)；不可用时返回 (None, None, 原因)。"""
    course = getattr(tc, "course", None)
    if course is None:
        return None, None, "缺少课程上下文，无法解析视觉模型配置。"
    async with SessionLocal() as db:
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course.id,
            AgentChatSession.module_type == "exercise",
        ))
        if not session or not session.image_model_config_id or not session.vision_model_config_id:
            return None, None, "图片生成或视觉复核模型未配置，请使用 exercise_degrade_visual 降级为文字材料。"
        image_config = await db.get(ModelConfig, session.image_model_config_id)
        vision_config = await db.get(ModelConfig, session.vision_model_config_id)
        if (
            not image_config or image_config.owner_id != course.owner_id
            or not vision_config or vision_config.owner_id != course.owner_id
            or "image_generation" not in (image_config.capabilities_json or [])
            or "vision_review" not in (vision_config.capabilities_json or [])
        ):
            return None, None, "图片生成或视觉复核模型配置不可用，请使用 exercise_degrade_visual 降级为文字材料。"
        return image_config, vision_config, ""


def _asset_relative(course_id: str, digest: str, suffix: str) -> Path:
    return Path("generated") / course_id / f"{digest}{suffix}"


def _question_context(builder, stimulus_id: str) -> dict:
    """从候选稿提取视觉材料所属题组的题目上下文，供视觉复核判断一致性。"""
    for section in builder.to_content().get("sections", []):
        for block in section.get("blocks", []):
            if block.get("kind") != "question_group":
                continue
            if any(stimulus.get("id") == stimulus_id for stimulus in block.get("stimuli", [])):
                return {
                    "group_title": block.get("title", ""),
                    "instructions": block.get("instructions", ""),
                    "questions": [
                        {"stem": item.get("stem"), "answer_key": item.get("answer_key")}
                        for item in block.get("sub_questions", [])
                    ],
                }
    return {"group_title": "", "instructions": "", "questions": []}


def _bind_visual_asset(tc: ToolContext, stimulus_id: str, visual_patch: dict) -> None:
    """更新 stimulus.visual 字段（asset_id/status/review_notes/provider 等）。"""
    builder = _builder(tc)
    builder.update_stimulus(stimulus_id, {"visual": visual_patch})


class RenderDiagramInput(BaseModel):
    stimulus_id: str = Field(description="题组材料 ID（kind=visual 的 stimulus）")
    visual_id: str = Field(description="视觉材料 ID")
    diagram_type: str = Field(description="coordinate / force / geometry / flow")
    diagram_spec: dict = Field(description="图示规格：points/arrows/nodes/labels 等")
    alt_text: str = Field(description="替代文本（灰度打印与无障碍）")
    fallback_stimulus: str = Field(description="等价文字替代材料（视觉不可用时展示）")
    caption: str = Field(default="", description="图题")


async def _exercise_render_diagram(tc: ToolContext, inp: RenderDiagramInput) -> ToolResult:
    """确定性渲染：LLM 提供规格，本地确定性 SVG 渲染器落图并绑定资产（approved）。"""
    from app.services.exercise_visual_service import render_deterministic_svg

    builder = _builder(tc)
    if inp.diagram_type not in {"coordinate", "force", "geometry", "flow"}:
        return ToolResult(ok=False, error=f"不支持的图示类型：{inp.diagram_type}", error_code="diagram_type_invalid", retryable=True)
    try:
        svg = render_deterministic_svg(inp.diagram_type, inp.diagram_spec, inp.alt_text)
    except Exception as exc:  # noqa: BLE001  规格非法由确定性渲染器拒绝
        return ToolResult(ok=False, error=f"图示规格无法渲染：{str(exc)[:200]}", error_code="diagram_spec_invalid", retryable=True)
    digest = hashlib.sha256(svg).hexdigest()
    course_id = getattr(getattr(tc, "course", None), "id", "unknown")
    relative = _asset_relative(course_id, digest, ".svg")
    target = get_settings().storage_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(svg)
    preview_relative = ""
    try:
        import cairosvg

        preview = cairosvg.svg2png(bytestring=svg, output_width=1440, output_height=900)
        preview_relative_path = _asset_relative(course_id, digest, ".png")
        preview_target = get_settings().storage_root / preview_relative_path
        if not preview_target.exists():
            preview_target.write_bytes(preview)
        preview_relative = str(preview_relative_path)
    except Exception:  # noqa: BLE001  预览非必需
        preview_relative = ""

    asset_id = ""
    async with SessionLocal() as db:
        asset = ArtifactAsset(
            owner_id=getattr(getattr(tc, "course", None), "owner_id", None),
            course_id=course_id,
            generation_run_id=getattr(tc, "generation_run_id", "") or None,
            json_path=f"$.stimuli[{inp.stimulus_id}].visual",
            asset_type="deterministic_diagram", relative_path=str(relative),
            preview_relative_path=preview_relative, mime_type="image/svg+xml",
            width=960, height=600, size_bytes=len(svg), checksum=digest,
            provider="deterministic_svg", model_name=inp.diagram_type, status="approved",
            review_json={"passed": True, "method": "typed_deterministic_renderer"},
        )
        db.add(asset)
        await db.flush()
        asset_id = asset.id
        await db.commit()
    visual_patch = {
        "visual_id": inp.visual_id, "mode": "deterministic_diagram",
        "purpose": inp.caption or "图示材料", "alt_text": inp.alt_text,
        "caption": inp.caption, "fallback_stimulus": inp.fallback_stimulus,
        "diagram_type": inp.diagram_type, "diagram_spec": dict(inp.diagram_spec),
        "asset_id": asset_id, "status": "approved", "provider": "deterministic_svg",
        "model_name": inp.diagram_type, "review_notes": [],
    }
    _bind_visual_asset(tc, inp.stimulus_id, visual_patch)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True, "asset_id": asset_id, "status": "approved",
        "diagram_type": inp.diagram_type,
        "note": "确定性图示已渲染并通过（typed deterministic renderer），无需视觉复核。",
    })


class GenerateImageInput(BaseModel):
    stimulus_id: str = Field(description="题组材料 ID（kind=visual 的 stimulus）")
    visual_id: str = Field(description="视觉材料 ID")
    generation_prompt: str = Field(description="生成式图片提示词（描述主体/环境/动作/风格，不含文字）")
    alt_text: str = Field(description="替代文本")
    fallback_stimulus: str = Field(description="等价文字替代材料")
    caption: str = Field(default="", description="图题")
    size: str = Field(default="1536x1024", description="1024x1024 / 1536x1024 / 1024x1536")


async def _exercise_generate_image(tc: ToolContext, inp: GenerateImageInput) -> ToolResult:
    """生成式图片：图片模型生成 + 视觉模型复核，通过则 approved；失败标记 degraded。"""
    from app.services.exercise_visual_service import generate_image, review_image

    builder = _builder(tc)
    image_config, vision_config, note = await _session_configs(tc)
    if image_config is None or vision_config is None:
        _bind_visual_asset(tc, inp.stimulus_id, {
            "visual_id": inp.visual_id, "mode": "generated_image",
            "purpose": inp.caption or "配图", "alt_text": inp.alt_text,
            "caption": inp.caption, "fallback_stimulus": inp.fallback_stimulus,
            "generation_prompt": inp.generation_prompt, "size": inp.size,
            "asset_id": None, "status": "degraded", "provider": "", "model_name": "",
            "review_notes": [note],
        })
        builder.bump_revision()
        return ToolResult(ok=False, error=note, error_code="vision_config_missing", retryable=False)
    question_context = _question_context(builder, inp.stimulus_id)
    last_issues: list[str] = []
    for _attempt in range(2):
        try:
            raw, mime = await generate_image(image_config, inp.generation_prompt, inp.size)
            review = await review_image(vision_config, raw, mime, question_context)
            if not review.passed:
                last_issues = review.issues
                continue
            digest = hashlib.sha256(raw).hexdigest()
            suffix = {".png": ".png", ".jpg": ".jpg", ".webp": ".webp"}.get(mime, ".png")
            course_id = getattr(getattr(tc, "course", None), "id", "unknown")
            relative = _asset_relative(course_id, digest, suffix)
            target = get_settings().storage_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(raw)
            asset_id = ""
            async with SessionLocal() as db:
                asset = ArtifactAsset(
                    owner_id=getattr(getattr(tc, "course", None), "owner_id", None),
                    course_id=course_id,
                    generation_run_id=getattr(tc, "generation_run_id", "") or None,
                    json_path=f"$.stimuli[{inp.stimulus_id}].visual",
                    asset_type="generated_image", relative_path=str(relative),
                    mime_type=mime, size_bytes=len(raw), checksum=digest,
                    provider=image_config.provider, model_name=image_config.model_name,
                    status="approved", review_json=review.model_dump(),
                )
                db.add(asset)
                await db.flush()
                asset_id = asset.id
                await db.commit()
            _bind_visual_asset(tc, inp.stimulus_id, {
                "visual_id": inp.visual_id, "mode": "generated_image",
                "purpose": inp.caption or "配图", "alt_text": inp.alt_text,
                "caption": inp.caption, "fallback_stimulus": inp.fallback_stimulus,
                "generation_prompt": inp.generation_prompt, "size": inp.size,
                "asset_id": asset_id, "status": "approved",
                "provider": image_config.provider, "model_name": image_config.model_name,
                "review_notes": [],
            })
            builder.bump_revision()
            return ToolResult(output={"ok": True, "asset_id": asset_id, "status": "approved"})
        except Exception as exc:  # noqa: BLE001  生成/复核失败重试
            last_issues = [str(exc)[:240]]
    _bind_visual_asset(tc, inp.stimulus_id, {
        "visual_id": inp.visual_id, "mode": "generated_image",
        "purpose": inp.caption or "配图", "alt_text": inp.alt_text,
        "caption": inp.caption, "fallback_stimulus": inp.fallback_stimulus,
        "generation_prompt": inp.generation_prompt, "size": inp.size,
        "asset_id": None, "status": "degraded", "provider": "", "model_name": "",
        "review_notes": last_issues,
    })
    builder.bump_revision()
    return ToolResult(
        ok=False, error="图片生成或视觉复核失败，已降级为待替代材料。",
        error_code="image_generation_failed", retryable=True,
        output={"status": "degraded", "issues": last_issues},
    )


class DegradeVisualInput(BaseModel):
    stimulus_id: str = Field(description="题组材料 ID（kind=visual 的 stimulus）")
    replacement_text: str = Field(description="等价文字替代材料（依据题干的文字版）")


async def _exercise_degrade_visual(tc: ToolContext, inp: DegradeVisualInput) -> ToolResult:
    """把视觉材料替换为等价文字替代材料（LLM 提供 replacement_text）。"""
    builder = _builder(tc)
    try:
        builder.update_stimulus(inp.stimulus_id, {
            "kind": "text", "title": "替代材料",
            "text": inp.replacement_text, "columns": [], "rows": [], "visual": None,
        })
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc), error_code="stimulus_not_found", retryable=True)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True, "stimulus_id": inp.stimulus_id, "kind": "text",
        "note": "视觉材料已降级为等价文字材料，学生仍可正常作答。",
    })


def _register_visual_tools() -> None:
    register_tool(Tool(
        "exercise_render_diagram", "确定性图示：提供规格渲染 SVG 并绑定资产（approved）",
        RenderDiagramInput, _exercise_render_diagram, timeout_seconds=30.0, idempotent=True,
    ))
    register_tool(Tool(
        "exercise_generate_image", "生成式图片：生成 + 视觉复核，通过则 approved；失败标记 degraded",
        GenerateImageInput, _exercise_generate_image, timeout_seconds=240.0,
    ))
    register_tool(Tool(
        "exercise_degrade_visual", "把视觉材料替换为等价文字替代材料",
        DegradeVisualInput, _exercise_degrade_visual,
    ))
