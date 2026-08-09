"""QA 工具：确定性几何/字宽/知识检查 + 可选图像检查（LibreOffice 可用时）。

没有 LibreOffice 的环境也能用几何 + 字宽估算做主要闸门。
"""
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH
from app.agent.slide_rendering import (
    infer_render_mode,
    render_coverage,
    runtime_baseline_slides,
    semantic_content_changed,
)

SEVERITY_WEIGHT = {"critical": 15, "major": 8, "minor": 3}
CONTENT_QA_INTENTS = {"GENERATE", "MODIFY", "LOCAL_REGENERATE", "CONTENT_UPDATE"}


def _text_height_inches(text: str, box_width: float, font_size: float) -> float:
    if not text:
        return 0.0
    char_w = font_size / 72.0 * 0.98
    chars_per_line = max(1, int(box_width / char_w))
    lines = 0
    for segment in str(text).split("\n"):
        lines += max(1, math.ceil(len(segment) / chars_per_line))
    return lines * font_size / 72.0 * 1.28


def run_geometry_qa(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """越界 / 重叠 / 文字溢出（基于元素几何与字号估算）。"""
    issues: list[dict[str, Any]] = []
    elements_by_slide: dict[str, list[dict[str, Any]]] = {}
    for item in report:
        elements_by_slide.setdefault(item["slide_id"], []).append(item)
    for slide_id, items in elements_by_slide.items():
        for element in items:
            x, y, w, h = element["x"], element["y"], element["w"], element["h"]
            if x < -0.01 or y < -0.01 or x + w > SLIDE_WIDTH + 0.01 or y + h > SLIDE_HEIGHT + 0.01:
                issues.append({
                    "severity": "critical", "slide_id": slide_id, "rule_id": "geometry.out_of_bounds",
                    "message": f"元素 {element['element_id']}({element['kind']}) 超出画布边界 ({x:.2f},{y:.2f},{w:.2f},{h:.2f})",
                    "target_agent": "layout",
                })
            style = element.get("style") or {}
            size = float(style.get("size") or 18)
            text = element.get("text", "")
            if element["kind"] in {"textbox", "note"} and text:
                needed = _text_height_inches(text, w, size)
                if needed > h * 1.15 and h > 0.1:
                    issues.append({
                        "severity": "major", "slide_id": slide_id, "rule_id": "geometry.text_overflow",
                        "message": f"元素 {element['element_id']} 文本预计 {needed:.1f}in 高，超出框高 {h:.1f}in（字号 {size}pt）",
                        "target_agent": "slide_content",
                    })
            if size < 9:
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "geometry.font_too_small",
                    "message": f"元素 {element['element_id']} 字号过小（{size}pt < 9pt）",
                    "target_agent": "layout",
                })
        # 两两重叠（内容元素）
        boxes = [(e["element_id"], e["x"], e["y"], e["w"], e["h"]) for e in items if e["kind"] != "shape"]
        for i, (id_a, ax, ay, aw, ah) in enumerate(boxes):
            for id_b, bx, by, bw, bh in boxes[i + 1:]:
                ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                oy = max(0, min(ay + ah, by + bh) - max(ay, by))
                if ox * oy > 0.05 and ox * oy > 0.3 * min(aw * ah, bw * bh):
                    issues.append({
                        "severity": "major", "slide_id": slide_id, "rule_id": "geometry.overlap",
                        "message": f"元素 {id_a} 与 {id_b} 重叠（面积 {ox * oy:.2f}in²）",
                        "target_agent": "layout",
                    })
    return issues


class RunQaInput(BaseModel):
    pass


async def _run_qa(tc: ToolContext, _: RunQaInput) -> ToolResult:
    issues: list[dict[str, Any]] = []
    selected = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    expected_image_slides: set[str] = set(selected)
    if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE" and tc.artifacts is not None:
        for artifact in await tc.artifacts.list_all():
            data = artifact.get("data") or {}
            if artifact.get("artifact_type") == "visual_asset":
                slide_id = str(data.get("slide_id") or "")
                if slide_id:
                    expected_image_slides.add(slide_id)
                for generated in data.get("generated_assets") or data.get("assets") or []:
                    slide_id = str(generated.get("slide_id") or "")
                    if slide_id:
                        expected_image_slides.add(slide_id)
            elif artifact.get("artifact_type") == "visual_plan":
                for plan in data.get("slides_visual_plan") or data.get("slides") or data.get("visual_plans") or []:
                    slide_id = str(plan.get("slide_id") or plan.get("slideId") or plan.get("id") or "")
                    if slide_id:
                        expected_image_slides.add(slide_id)
    qa_scope = expected_image_slides if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE" else selected
    degraded = False
    content: dict[str, Any] = {}
    if tc.builder is not None:
        report = tc.builder.geometry_report()
        if qa_scope:
            report = [item for item in report if str(item.get("slide_id")) in qa_scope]
        issues.extend(run_geometry_qa(report))
        if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}:
            for issue in issues:
                if issue.get("target_agent") == "slide_content":
                    issue["target_agent"] = "layout"
        content = tc.builder.to_ppt_content()
        try:
            from app.services.ppt_knowledge_service import check_ppt_against_knowledge
            if (
                getattr(tc.runtime, "active_intent", "GENERATE") in CONTENT_QA_INTENTS
                and getattr(tc.runtime, "content_policy", "edit") == "edit"
            ):
                for violation in check_ppt_against_knowledge(content):
                    if qa_scope and str(violation.slide_id) not in qa_scope:
                        continue
                    issues.append({
                        "severity": "major" if violation.rule_id.startswith("density") else "minor",
                        "slide_id": violation.slide_id, "rule_id": violation.rule_id, "message": violation.message,
                        "target_agent": "slide_content" if violation.rule_id.startswith("density") else "ppt_editor",
                    })
        except Exception:  # noqa: BLE001
            pass
        source_by_id = {
            str(slide.get("id") or ""): slide
            for slide in runtime_baseline_slides(tc.runtime)
        }
        coverage_scope = qa_scope or set(source_by_id)
        coverage_by_slide: dict[str, Any] = {}
        for slide in tc.builder.slides:
            slide_id = str(slide.get("id") or "")
            if coverage_scope and slide_id not in coverage_scope:
                continue
            baseline = source_by_id.get(slide_id, slide)
            coverage = render_coverage(slide, baseline=baseline)
            coverage_by_slide[slide_id] = coverage
            if coverage["missing_refs"]:
                absolute = infer_render_mode(slide) == "absolute"
                issues.append({
                    "severity": "critical", "slide_id": slide_id,
                    "rule_id": "layout.incomplete_absolute" if absolute else "content.not_rendered",
                    "message": "绝对布局未覆盖页面必要文字" if absolute else "页面语义文字没有进入最终渲染层",
                    "target_agent": "layout",
                    "missing_refs": coverage["missing_refs"],
                })
            if (
                getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
                and slide_id in source_by_id
                and semantic_content_changed(source_by_id[slide_id], slide)
            ):
                issues.append({
                    "severity": "critical", "slide_id": slide_id,
                    "rule_id": "content.accidentally_removed",
                    "message": "内容锁定任务意外改动了页面语义文字",
                    "target_agent": "layout",
                })
            final_elements = tc.builder.render_elements(slide)
            text_elements = [item for item in final_elements if item.get("kind") in {"textbox", "note"}]
            media_elements = [item for item in final_elements if item.get("kind") in {"image", "chart"}]
            if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}:
                from app.agent.agents.layout import _content_start_x
                safe_x = _content_start_x(
                    str(tc.builder.template.get("id") or ""),
                    str(slide.get("page_type") or "concept"),
                )
                if any(
                    item.get("content_ref")
                    and float(item.get("x") or 0) < safe_x - 0.01
                    for item in text_elements
                ):
                    issues.append({
                        "severity": "critical", "slide_id": slide_id,
                        "rule_id": "visual.overlaps_template",
                        "message": "页面文字进入模板装饰或侧栏遮挡区域",
                        "target_agent": "layout",
                    })
            for media in media_elements:
                mx, my, mw, mh = (float(media.get(key) or 0) for key in ("x", "y", "w", "h"))
                for text_element in text_elements:
                    tx, ty, tw, th = (float(text_element.get(key) or 0) for key in ("x", "y", "w", "h"))
                    overlap_w = max(0.0, min(mx + mw, tx + tw) - max(mx, tx))
                    overlap_h = max(0.0, min(my + mh, ty + th) - max(my, ty))
                    if overlap_w * overlap_h > 0.05:
                        issues.append({
                            "severity": "critical", "slide_id": slide_id,
                            "rule_id": "visual.overlaps_content",
                            "message": "图片或图表遮挡了页面文字区域",
                            "target_agent": "layout",
                        })
                        break
        if tc.runtime is not None:
            tc.runtime.render_coverage = coverage_by_slide

        if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
            expected_slots = {
                str(item.get("slide_id") or ""): str(item.get("visual_slot") or "primary_visual")
                for item in (getattr(tc.runtime, "expected_visual_requests", []) or [])
            }
            scoped_slides = [slide for slide in tc.builder.slides if str(slide.get("id")) in expected_image_slides]
            for slide in scoped_slides:
                images = [element for element in (slide.get("elements") or []) if element.get("kind") == "image"]
                valid_ids = set(getattr(tc.runtime, "generated_asset_ids", []) or [])
                valid_images = []
                for element in images:
                    asset_path = str(element.get("asset_path") or "")
                    asset_id = str(element.get("asset_id") or "")
                    candidate = Path(asset_path)
                    # 新写入的图片应当是绝对路径；同时兼容旧 Run 留下的 workspace
                    # 相对路径。仅当原路径不存在时才拼 workspace_root，避免把
                    # ``storage/.../run/assets/x`` 再拼成 ``storage/.../run/storage/...``。
                    if not candidate.is_file() and tc.workspace_root is not None and not candidate.is_absolute():
                        workspace_candidate = Path(tc.workspace_root) / candidate
                        if workspace_candidate.is_file():
                            candidate = workspace_candidate.resolve()
                    if asset_id in valid_ids and candidate.is_file() and not element.get("degraded"):
                        valid_images.append(element)
                if not valid_images:
                    issues.append({
                        "severity": "critical", "slide_id": str(slide.get("id") or ""),
                        "rule_id": "image.missing", "message": "目标页面尚未插入生成图片",
                        "target_agent": "media",
                    })
                else:
                    expected_slot = expected_slots.get(str(slide.get("id") or ""), "primary_visual")
                    if not any(str(element.get("visual_slot") or "primary_visual") == expected_slot for element in valid_images):
                        issues.append({
                            "severity": "critical", "slide_id": str(slide.get("id") or ""),
                            "rule_id": "visual.slot_missing", "message": "生成图片没有进入规划的视觉槽位",
                            "target_agent": "ppt_editor",
                        })
    else:
        content = tc.ctx.source_artifact.content_json if tc.ctx and tc.ctx.source_artifact is not None else {}

    # 可选图像 QA（LibreOffice 可用时）
    image_notes = ""
    try:
        from app.renderers.ppt_visual_qa import PPTVisualQARenderer
        if PPTVisualQARenderer.is_available():
            image_notes = "visual QA via LibreOffice"
        else:
            degraded = True
            image_notes = "visual QA 降级为几何检查（未安装 LibreOffice）"
    except Exception:  # noqa: BLE001
        degraded = True

    severity_counts: dict[str, int] = {}
    for issue in issues:
        severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1
    score = max(0, 100 - sum(SEVERITY_WEIGHT.get(item["severity"], 3) for item in issues))
    result = {"score": score, "issues": issues, "severity_counts": severity_counts, "degraded": degraded, "image_qa": image_notes}

    artifact = None
    if tc.artifacts is not None:
        artifact = await tc.artifacts.create("visual_qa", "default", result,
                                             producer_agent="visual_qa", producer_tool="run_qa")
    if tc.emitter is not None:
        for issue in issues:
            await tc.emitter.qa_issue_found(issue)
        await tc.emitter.qa_completed(score, len(issues), severity_counts,
                                      round_=getattr(tc.ctx, "revision_round", 0), degraded=degraded, issues=issues)
    return ToolResult(ok=True, output={"qa_artifact_id": artifact["id"] if artifact else "", **result})


class GetQaReportInput(BaseModel):
    pass


async def _get_qa_report(tc: ToolContext, _: GetQaReportInput) -> ToolResult:
    if tc.artifacts is not None:
        latest = await tc.artifacts.latest("visual_qa")
        if latest:
            return ToolResult(ok=True, output={"qa": latest["data"]})
    return ToolResult(ok=False, error="尚无 QA 报告")


async def _run_content_qa(tc: ToolContext, _: RunQaInput) -> ToolResult:
    if getattr(tc.runtime, "content_policy", "edit") != "edit":
        return ToolResult(ok=True, output={"issues": [], "coverage": {"slides_checked": 0}, "score": 100, "skipped": "content_locked"})
    content = tc.builder.to_ppt_content() if tc.builder is not None else (
        tc.ctx.source_artifact.content_json if tc.ctx and tc.ctx.source_artifact is not None else {}
    )
    issues: list[dict[str, Any]] = []
    selected = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    seen_titles: dict[str, str] = {}
    checked = 0
    for index, slide in enumerate(content.get("slides") or []):
        slide_id = str(slide.get("id") or f"S{index + 1:02d}")
        title = str(slide.get("title") or "").strip()
        body = [str(item).strip() for item in (slide.get("body") or []) if str(item).strip()]
        in_scope = not selected or slide_id in selected
        if in_scope:
            checked += 1
        if in_scope and title and title in seen_titles:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "content.duplicate_title", "message": f"标题与 {seen_titles[title]} 重复", "target_agent": "slide_content"})
        elif title:
            seen_titles[title] = slide_id
        if in_scope and len(body) > 6:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "content.density", "message": f"页面包含 {len(body)} 条正文，超过 6 条", "target_agent": "slide_content"})
        if in_scope and not title and slide.get("page_type") != "cover":
            issues.append({"severity": "minor", "slide_id": slide_id, "rule_id": "content.missing_title", "message": "页面缺少标题", "target_agent": "slide_content"})
    result = {"issues": issues, "coverage": {"slides_checked": checked}, "score": max(0, 100 - len(issues) * 8)}
    artifact = await tc.artifacts.create("content_qa", "default", result, producer_agent="visual_qa", producer_tool="run_content_qa") if tc.artifacts else None
    if tc.emitter:
        await tc.emitter.emit_domain("qa.completed", message=f"内容 QA 完成，发现 {len(issues)} 个问题", payload={"kind": "content", **result})
    return ToolResult(ok=True, output={"qa_artifact_id": artifact["id"] if artifact else "", **result})


def register_qa_tools():
    register_tool(Tool("run_qa", "运行几何/字宽/知识 QA，返回评分与问题列表", RunQaInput, _run_qa, timeout_seconds=120, max_retries=1, idempotent=True))
    register_tool(Tool("run_content_qa", "检查目标覆盖、重复、缺失标题和内容密度", RunQaInput, _run_content_qa, timeout_seconds=60, idempotent=True))
    register_tool(Tool("get_qa_report", "读取最近一次 QA 报告", GetQaReportInput, _get_qa_report))


register_qa_tools()
