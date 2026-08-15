#!/usr/bin/env python3
"""Dry-run or atomically create a repaired lesson-plan version from V16."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.agents.lesson_plan.recovery import (
    REPAIR_SUMMARY,
    build_assessment_reflection_repair,
    validate_assessment_reflection_repair,
)
from app.models.entities import Artifact, CourseBlueprint, CourseTask
from app.services.course_task_service import register_artifact_version


def online_backup(database: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"备份文件已存在：{destination}")
    source = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


async def repair(args: argparse.Namespace) -> dict:
    database = args.db.resolve()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            if args.apply:
                await db.execute(text("BEGIN IMMEDIATE"))
            source = await db.scalar(select(Artifact).where(
                Artifact.course_id == args.course_id,
                Artifact.artifact_type == "lesson_plan",
                Artifact.version == args.source_version,
            ))
            damaged = await db.scalar(select(Artifact).where(
                Artifact.course_id == args.course_id,
                Artifact.artifact_type == "lesson_plan",
                Artifact.version == args.damaged_version,
            ))
            task = await db.scalar(select(CourseTask).where(
                CourseTask.course_id == args.course_id,
                CourseTask.task_type == "lesson_plan",
            ))
            if not source or not damaged or not task:
                raise RuntimeError("缺少源版本、损坏版本或教学设计任务")
            expected_current = args.expected_current_artifact_id or damaged.id
            if task.current_artifact_id != expected_current:
                raise RuntimeError(
                    f"当前 Artifact 已变化：期望 {expected_current}，实际 {task.current_artifact_id}"
                )
            existing = await db.scalar(select(Artifact).where(
                Artifact.course_id == args.course_id,
                Artifact.artifact_type == "lesson_plan",
                Artifact.change_summary == REPAIR_SUMMARY,
            ).order_by(Artifact.version.desc()))
            if existing:
                raise RuntimeError(f"修复版本已存在：V{existing.version} ({existing.id})")
            latest_version = await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == args.course_id,
                Artifact.artifact_type == "lesson_plan",
            )) or 0
            if latest_version != damaged.version:
                raise RuntimeError(f"最新版本不是损坏版本 V{damaged.version}，实际为 V{latest_version}")
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == args.course_id,
                CourseBlueprint.version == source.blueprint_version,
            ))
            if not blueprint:
                raise RuntimeError("缺少源版本对应的课程蓝图")

            candidate = build_assessment_reflection_repair(source.content_json)
            checked = validate_assessment_reflection_repair(
                source.content_json,
                candidate,
                blueprint.content_json,
            )
            result = {
                "mode": "apply" if args.apply else "dry-run",
                "source_version": source.version,
                "damaged_version": damaged.version,
                "target_version": latest_version + 1,
                "diff": checked["diff"],
                "markdown_chars": len(checked["markdown"]),
                "backup": str(args.backup.resolve()) if args.backup else "",
            }
            if not args.apply:
                await db.rollback()
                return result

            artifact = Artifact(
                course_id=source.course_id,
                artifact_type="lesson_plan",
                version=latest_version + 1,
                blueprint_version=source.blueprint_version,
                content_json=checked["content"],
                content_markdown=checked["markdown"],
                status="draft",
                model_name=source.model_name,
                prompt_version=source.prompt_version,
                change_summary=REPAIR_SUMMARY,
                source_versions_json=dict(source.source_versions_json or {}),
                agent_profile_id=source.agent_profile_id,
            )
            db.add(artifact)
            await db.flush()
            await register_artifact_version(db, artifact, invalidate_dependents=True)
            await db.commit()
            result["artifact_id"] = artifact.id
            return result
    finally:
        await engine.dispose()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=root / "storage" / "app.db")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--source-version", type=int, default=16)
    parser.add_argument("--damaged-version", type=int, default=17)
    parser.add_argument("--expected-current-artifact-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and not args.backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.backup = root / "storage" / "backups" / f"app-before-lesson-v18-{stamp}.db"
    if args.apply:
        online_backup(args.db, args.backup)
    result = asyncio.run(repair(args))
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
