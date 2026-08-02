from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import get_db
from app.models.entities import QualityIssue, QualityReport, User

router = APIRouter(tags=["质量"])


@router.get("/courses/{course_id}/quality/latest")
async def latest_quality(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    report = await db.scalar(select(QualityReport).where(QualityReport.course_id == course_id).order_by(QualityReport.created_at.desc()))
    if not report:
        raise HTTPException(404, "尚无质量报告")
    issues = list(await db.scalars(select(QualityIssue).where(QualityIssue.report_id == report.id)))
    return {"id": report.id, "score": report.score, "dimensions": report.dimensions_json, "summary": report.summary, "issues": [{key: getattr(x, key) for key in ("id", "severity", "artifact_type", "location", "dimension", "description", "evidence", "suggestion", "target_agent", "required_action", "status")} for x in issues]}


@router.patch("/quality/issues/{issue_id}")
async def update_issue(issue_id: str, status: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(QualityIssue, issue_id)
    if not item:
        raise HTTPException(404, "问题不存在")
    report = await db.get(QualityReport, item.report_id)
    await owned_course(report.course_id, user, db)
    item.status = status
    await db.commit()
    return {"id": item.id, "status": item.status}

