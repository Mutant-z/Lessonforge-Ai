"""Versioned PPT and slide artifact persistence."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.entities import (
    Artifact, GenerationRun, PipelineRun, PPTRevision, PPTSlideArtifact, PPTSlideRevision,
)


def _slide_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"kind": "created", "changed_fields": sorted(current)}
    changed = [key for key in sorted(set(previous) | set(current)) if previous.get(key) != current.get(key)]
    return {"kind": "updated" if changed else "unchanged", "changed_fields": changed}


async def record_ppt_revision(
    db,
    *,
    run: GenerationRun,
    artifact: Artifact,
    content: dict[str, Any],
    source: Artifact | None,
    change_summary: str,
) -> PPTRevision:
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run.id))
    parent = await db.scalar(select(PPTRevision).where(
        PPTRevision.course_id == artifact.course_id,
    ).order_by(PPTRevision.version.desc()))
    revision = PPTRevision(
        course_id=artifact.course_id,
        pipeline_run_id=pipeline.id if pipeline else None,
        artifact_id=artifact.id,
        parent_id=parent.id if parent else None,
        version=artifact.version,
        template_id=str(content.get("theme") or ""),
        status="draft",
        change_summary=change_summary,
        snapshot_json={"slide_count": len(content.get("slides") or []), "theme": content.get("theme")},
    )
    db.add(revision)
    await db.flush()
    previous_by_id = {
        str(slide.get("id") or f"S{index + 1:02d}"): slide
        for index, slide in enumerate((source.content_json if source else {}).get("slides") or [])
    }
    for index, slide in enumerate(content.get("slides") or []):
        slide_id = str(slide.get("id") or f"S{index + 1:02d}")
        previous_slide = await db.scalar(select(PPTSlideArtifact).where(
            PPTSlideArtifact.ppt_revision_id == parent.id,
            PPTSlideArtifact.slide_id == slide_id,
        )) if parent else None
        previous_revision = await db.scalar(select(PPTSlideRevision).where(
            PPTSlideRevision.slide_artifact_id == previous_slide.id,
        ).order_by(PPTSlideRevision.revision.desc())) if previous_slide else None
        slide_revision_number = (previous_revision.revision if previous_revision else 0) + 1
        slide_artifact = PPTSlideArtifact(
            ppt_revision_id=revision.id,
            pipeline_run_id=pipeline.id if pipeline else None,
            slide_id=slide_id,
            page_number=index + 1,
            current_revision=slide_revision_number,
            status="ready",
            qa_status="passed",
            data_json=slide,
        )
        db.add(slide_artifact)
        await db.flush()
        db.add(PPTSlideRevision(
            slide_artifact_id=slide_artifact.id,
            parent_id=previous_revision.id if previous_revision else None,
            revision=slide_revision_number,
            data_json=slide,
            diff_json=_slide_diff(previous_by_id.get(slide_id), slide),
            change_summary=change_summary,
        ))
    return revision
