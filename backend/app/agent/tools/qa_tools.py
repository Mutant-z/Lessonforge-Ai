"""QA 工具：确定性几何/字宽/知识检查 + 可选图像检查（LibreOffice 可用时）。

没有 LibreOffice 的环境也能用几何 + 字宽估算做主要闸门。
"""
import math
from typing import Any

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH

SEVERITY_WEIGHT = {"critical": 15, "major": 8, "minor": 3}


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
    degraded = False
    content: dict[str, Any] = {}
    if tc.builder is not None:
        report = tc.builder.geometry_report()
        issues.extend(run_geometry_qa(report))
        content = tc.builder.to_ppt_content()
        try:
            from app.services.ppt_knowledge_service import check_ppt_against_knowledge
            for violation in check_ppt_against_knowledge(content):
                issues.append({
                    "severity": "major" if violation.rule_id.startswith("density") else "minor",
                    "slide_id": violation.slide_id, "rule_id": violation.rule_id, "message": violation.message,
                    "target_agent": "slide_content" if violation.rule_id.startswith("density") else "ppt_editor",
                })
        except Exception:  # noqa: BLE001
            pass
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


def register_qa_tools():
    register_tool(Tool("run_qa", "运行几何/字宽/知识 QA，返回评分与问题列表", RunQaInput, _run_qa))
    register_tool(Tool("get_qa_report", "读取最近一次 QA 报告", GetQaReportInput, _get_qa_report))


register_qa_tools()
