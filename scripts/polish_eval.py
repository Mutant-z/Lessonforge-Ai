#!/usr/bin/env python3
"""PPT 润色引擎人工抽查报告工具。

读取 storage/generated/ 下最近一次真实生成的 PPT 页面语义内容
（ppt_pipeline/<run>/plans/slide_content_*.json），对每条润色指令用确定性布局引擎
compile_layout 分别编译 before（润色前窄条失败形态）与 after（引擎修复后）两版，
渲染 PNG 蓝图图，并输出每页几何 QA 摘要到 storage/polish_eval/report.md，
供人工判定合格率。

用法（在仓库根目录）:
    python scripts/polish_eval.py
（脚本会自行把 backend 加入 sys.path，任意 cwd 均可运行。）
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TEMPLATE_ID = "lessonforge_deck_academic"
OUT_DIR = ROOT / "storage" / "polish_eval"
BLUEPRINT_DIR = OUT_DIR / "blueprints"

CASES = [
    {"instruction": "润色一下现在PPT的页面分布", "modality": "layout", "layout_type": "bullet_flow"},
    {"instruction": "这段文字太挤了，调整一下间距和留白", "modality": "layout", "layout_type": "bullet_flow"},
    {"instruction": "让正文条目间隔大一点", "modality": "layout", "layout_type": "bullet_flow"},
    {"instruction": "页面右侧太空，平衡一下", "modality": "layout", "layout_type": "split_two_column"},
]

# 与 qa_tools.run_geometry_qa 规则保持一致的轻量几何检查。
# 刻意不 import qa_tools：它依赖并发 wave 正在修改的 agents/layout.py，
# 本工具必须随时可运行。
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5
MARGIN_Y, SAFE_CONTENT_BOTTOM = 1.7, 6.8
MIN_BODY_VERTICAL_USAGE = 0.45
FULL_BODY_W = SLIDE_WIDTH - 1.3


def _cram_issues(elements) -> list[str]:
    """轻量几何 QA：返回命中的规则 id 列表（越界/窄条/纵向未铺满/右侧空白）。"""
    text = [
        el for el in (elements or [])
        if el.get("kind") in {"textbox", "note"} and el.get("content_ref") != "title"
    ]
    issues: list[str] = []
    if not text:
        return issues
    xs, ys, rights, bottoms = [], [], [], []
    for el in text:
        x, y, w, h = (float(el.get(k) or 0) for k in ("x", "y", "w", "h"))
        xs.append(x)
        ys.append(y)
        rights.append(x + w)
        bottoms.append(y + h)
        if x < -0.01 or y < -0.01 or x + w > SLIDE_WIDTH + 0.01 or y + h > SLIDE_HEIGHT + 0.01:
            issues.append("geometry.out_of_bounds")
    span_w = max(rights) - min(xs)
    span_h = max(bottoms) - min(ys)
    content_h = SAFE_CONTENT_BOTTOM - MARGIN_Y
    if span_w < 4.0:
        issues.append("layout.cluster_cramming")
    if span_h < content_h * MIN_BODY_VERTICAL_USAGE and span_w < FULL_BODY_W * 0.6:
        issues.append("layout.vertical_underuse")
    if span_h >= content_h * MIN_BODY_VERTICAL_USAGE and span_w < FULL_BODY_W * 0.45:
        issues.append("layout.column_balance")
    return issues


def find_slides() -> tuple[str, str, list[dict]]:
    """返回 (course_id, run_id, slides)。无真实生成内容时返回空 slides。"""
    gen_root = ROOT / "storage" / "generated"
    if not gen_root.is_dir():
        return ("", "", [])
    for run_dir in sorted(gen_root.iterdir(), key=lambda p: p.name, reverse=True):
        pipeline_root = run_dir / "ppt_pipeline"
        if not pipeline_root.is_dir():
            continue
        for plan_root in sorted(pipeline_root.iterdir(), key=lambda p: p.name, reverse=True):
            plans_dir = plan_root / "plans"
            plans = sorted(plans_dir.glob("slide_content_*.json")) if plans_dir.is_dir() else []
            if not plans:
                continue
            try:
                data = json.loads(plans[-1].read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            slides = data.get("slides") or []
            if slides:
                return (run_dir.name, plan_root.name, slides)
    return ("", "", [])


def _intent_label(instruction: str) -> str:
    try:
        from app.agent.runtime import infer_intent
        return infer_intent("message", instruction, ["S01"])
    except Exception:  # noqa: BLE001 — runtime 可能在并发 wave 半途保存，降级为静态标签
        return "LAYOUT_ONLY"


def _crammed_before(slide: dict) -> dict:
    """构造润色前的窄条失败形态：正文被压成 1.5in 窄条堆在左上方。"""
    from app.agent.slide_rendering import semantic_body_refs

    title = str(slide.get("title") or "")
    elements = [{
        "kind": "textbox", "role": "title", "content_ref": "title", "text": title,
        "x": 2.2, "y": 0.55, "w": 6.0, "h": 0.8, "style": {"size": 28, "bold": True},
    }]
    y = MARGIN_Y
    for ref, text in semantic_body_refs(slide) or []:
        elements.append({
            "kind": "textbox", "role": "body", "content_ref": ref, "text": text,
            "x": 2.2, "y": y, "w": 1.5, "h": 0.5, "style": {"size": 18},
        })
        y += 0.6
    return {
        "slide_id": str(slide.get("id") or ""), "layout_type": "crammed",
        "designRationale": "润色前失败形态（窄条堆叠）", "render_mode": "absolute",
        "elements": elements,
    }


def _compile(slide: dict, layout_type: str) -> dict:
    """确定性引擎编译一页；封面页映射到 cover_left。"""
    from app.agent.layouts.engine import compile_layout

    page_type = str(slide.get("page_type") or "concept")
    effective = "cover_left" if page_type == "cover" else layout_type
    return compile_layout(
        TEMPLATE_ID, slide,
        {"slide_id": str(slide.get("id") or ""), "layout_type": effective},
    )


def _render_blueprint(spec: dict, page_type: str) -> str:
    from app.agent.layouts.zones import zones_for
    from app.agent.tools.vision_tools import render_geometry_preview

    zones = zones_for(
        TEMPLATE_ID, page_type,
        has_visual=bool(spec.get("visual_region")), visual_region=spec.get("visual_region"),
    )
    return render_geometry_preview(spec, zones)


def _save_blueprint(png_b64: str, name: str) -> pathlib.Path:
    path = BLUEPRINT_DIR / name
    path.write_bytes(base64.b64decode(png_b64))
    return path


def _conclusion(before: list[str], after: list[str]) -> str:
    if before and not after:
        return "已修复"
    if before and after:
        return "未达标"
    if not before and after:
        return "引入问题"
    return "无异常"


async def main() -> int:
    course_id, run_id, slides = find_slides()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BLUEPRINT_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# PPT 润色引擎人工抽查报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("- 引擎：`compile_layout` 确定性布局引擎（presets + zones）")
    lines.append("- 方法：before = 润色前失败形态（窄条堆叠）；after = 引擎编译结果；两版均渲染蓝图 PNG 并做几何 QA")

    if not slides:
        lines.append("")
        lines.append("## 无可用真实 PPT 内容")
        lines.append("")
        lines.append("`storage/generated/` 下未找到 `ppt_pipeline/*/plans/slide_content_*.json`。")
        lines.append("请先生成一份 PPT 后再运行本工具，页面级抽查将自动启用。")
        (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[polish_eval] 未找到真实 PPT 内容，已写空报告 {OUT_DIR / 'report.md'}")
        return 0

    lines.append(f"- 输入源：`storage/generated/{course_id}/ppt_pipeline/{run_id}/plans/slide_content_*.json`（{len(slides)} 页）")
    lines.append("")
    lines.append(f"总计 {len(CASES)} 条用例 × {len(slides)} 页 = {len(CASES) * len(slides)} 行。")
    lines.append("")

    stats = {"rows": 0, "fixed": 0, "failed": 0}
    for case_index, case in enumerate(CASES):
        instruction = case["instruction"]
        layout_type = case["layout_type"]
        intent = _intent_label(instruction)
        lines.append(f"## 用例 {case_index + 1}：{instruction}（{intent}）")
        lines.append("")
        lines.append("| 页面 | 页型 | after 布局 | before QA | after QA | 结论 |")
        lines.append("|---|---|---|---|---|---|")
        image_rows: list[str] = []
        for slide in slides:
            slide_id = str(slide.get("id") or "")
            page_type = str(slide.get("page_type") or "concept")
            try:
                before = _crammed_before(slide)
                after = _compile(slide, layout_type)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"| {slide_id} | {page_type} | 编译失败 | - | - | {type(exc).__name__} |")
                stats["failed"] += 1
                continue
            before_issues = _cram_issues(before["elements"])
            after_issues = _cram_issues(after["elements"])
            conclusion = _conclusion(before_issues, after_issues)
            stats["rows"] += 1
            if conclusion == "已修复":
                stats["fixed"] += 1
            elif conclusion in {"未达标", "引入问题"}:
                stats["failed"] += 1

            before_name = f"case{case_index + 1}-{slide_id}-before.png"
            after_name = f"case{case_index + 1}-{slide_id}-after.png"
            _save_blueprint(_render_blueprint(before, page_type), before_name)
            _save_blueprint(_render_blueprint(after, page_type), after_name)

            lines.append(
                f"| {slide_id} | {page_type} | {after.get('layout_type')} | "
                f"{'、'.join(before_issues) or 'ok'} | {'、'.join(after_issues) or 'ok'} | {conclusion} |"
            )
            image_rows.append(
                f"- {slide_id}：![before](blueprints/{before_name}) ![after](blueprints/{after_name})"
            )
        lines.append("")
        if image_rows:
            lines.append("**蓝图 before/after：**")
            lines.extend(image_rows)
            lines.append("")
        lines.append("---")
        lines.append("")

    pass_rate = (stats["fixed"] / stats["rows"] * 100) if stats["rows"] else 0.0
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- 总行数：{stats['rows']}；已修复：{stats['fixed']}；未达标/失败：{stats['failed']}")
    lines.append(f"- 合格率（after 无挤压/空白类问题）：{pass_rate:.0f}%")
    lines.append("")
    lines.append("> 蓝图图为 PNG，使用支持图片预览的 Markdown 查看器打开本报告即可对照 before/after。")
    report = "\n".join(lines) + "\n"
    report_path = OUT_DIR / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[polish_eval] 已写报告 {report_path}（{stats['rows']} 行，合格率 {pass_rate:.0f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
