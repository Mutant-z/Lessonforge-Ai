#!/usr/bin/env python3
"""Read-only audit for completed lesson-plan agent runs.

The database is opened with SQLite ``mode=ro``.  The script prints Markdown and
never updates runs or Artifacts.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def _json(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def audit(db_path: Path) -> str:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    runs = connection.execute(
        """
        SELECT pr.id AS pipeline_run_id, gr.id AS generation_run_id,
               gr.status AS generation_status, gr.created_at, gr.finished_at,
               pr.status AS pipeline_status, pr.plan_json, ct.course_id
          FROM pipeline_runs pr
          JOIN generation_runs gr ON gr.id = pr.generation_run_id
          JOIN course_tasks ct ON ct.id = gr.course_task_id
         WHERE ct.task_type = 'lesson_plan'
         ORDER BY gr.created_at DESC
        """
    ).fetchall()
    lines = [
        "# 教学设计 Agent 运行审计",
        "",
        f"数据库：`{db_path.resolve()}`（只读）",
        "",
        "| 运行时间 | Generation Run | Pipeline Run | 状态 | 风险 |",
        "|---|---|---|---|---|",
    ]
    flagged = 0
    for row in runs:
        pipeline_id = row["pipeline_run_id"]
        plan = _json(row["plan_json"], {})
        failed_tools = connection.execute(
            "SELECT COUNT(*) FROM pipeline_tool_calls WHERE pipeline_run_id=? AND status='failed'",
            (pipeline_id,),
        ).fetchone()[0]
        artifacts = {
            item[0] for item in connection.execute(
                "SELECT DISTINCT artifact_type FROM pipeline_artifacts WHERE pipeline_run_id=?",
                (pipeline_id,),
            ).fetchall()
        }
        intent = str(plan.get("active_intent") or "")
        result = str(plan.get("result_status") or "")
        expected = {"lesson_qa", "lesson_plan_draft"}
        if intent in {"RESTRUCTURE", "SECTION_EDIT"}:
            expected |= {"lesson_intent", "lesson_research", "lesson_outline", "lesson_content"}
        missing = sorted(expected - artifacts) if intent else []
        diff = plan.get("diff_summary") if isinstance(plan.get("diff_summary"), dict) else {}
        legacy_diff = connection.execute(
            """
            SELECT output_json FROM pipeline_tool_calls
             WHERE pipeline_run_id=? AND tool_name='lesson_diff_versions' AND status='completed'
             ORDER BY created_at DESC LIMIT 1
            """,
            (pipeline_id,),
        ).fetchone()
        legacy_diff = _json(legacy_diff[0], {}) if legacy_diff else {}
        risks = []
        if row["generation_status"] == "completed" and failed_tools:
            risks.append(f"完成但含 {failed_tools} 个失败工具")
        if missing:
            risks.append("缺少产物：" + ", ".join(missing))
        if intent == "RESTRUCTURE" and result == "applied":
            structure_changed = diff.get("outline_structure_changed")
            if structure_changed is False or (structure_changed is None and legacy_diff.get("changed") is False):
                risks.append("结构意图没有结构 diff")
            elif structure_changed is None:
                risks.append("旧运行未记录结构 diff，需复核")
        risk_text = "；".join(risks) if risks else "—"
        if risks:
            flagged += 1
        lines.append(
            f"| {row['created_at']} | `{row['generation_run_id']}` | `{pipeline_id}` | "
            f"{row['generation_status']}/{row['pipeline_status']} | {risk_text} |"
        )
    lines.extend(["", f"共审计 {len(runs)} 次运行，标记 {flagged} 次需复核。", ""])

    artifacts = connection.execute(
        """
        SELECT id, course_id, version, content_json, content_markdown, created_at
          FROM artifacts
         WHERE artifact_type='lesson_plan'
         ORDER BY course_id, version
        """
    ).fetchall()
    lines.extend([
        "## Artifact 内容退化审计",
        "",
        "| 课程 | 版本 | Artifact | 风险 |",
        "|---|---:|---|---|",
    ])
    previous_by_course = {}
    artifact_flagged = 0
    for row in artifacts:
        content = _json(row["content_json"], {})
        empty_leaf_ids = []

        def visit(items):
            for item in items or []:
                children = item.get("children") or []
                if children:
                    visit(children)
                elif not (item.get("blocks") or []) and not str(item.get("summary") or "").strip():
                    empty_leaf_ids.append(str(item.get("id") or ""))

        visit((content.get("outline") or {}).get("sections") or [])
        risks = []
        if empty_leaf_ids:
            risks.append("空叶子章节：" + ", ".join(empty_leaf_ids))
        previous = previous_by_course.get(row["course_id"])
        current_length = len(row["content_markdown"] or "")
        if previous and previous["markdown_length"] > 0 and current_length < previous["markdown_length"] * 0.5:
            risks.append(
                f"Markdown 较 V{previous['version']} 下降超过 50%"
            )
        if risks:
            artifact_flagged += 1
            lines.append(
                f"| `{row['course_id']}` | V{row['version']} | `{row['id']}` | {'；'.join(risks)} |"
            )
        previous_by_course[row["course_id"]] = {
            "version": row["version"],
            "markdown_length": current_length,
        }
    if not artifact_flagged:
        lines.append("| — | — | — | 未发现内容退化 |")
    lines.extend(["", f"共审计 {len(artifacts)} 个教学设计版本，标记 {artifact_flagged} 个异常版本。", ""])
    connection.close()
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=root / "storage" / "app.db")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.db)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
