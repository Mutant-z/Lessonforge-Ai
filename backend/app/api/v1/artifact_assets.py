from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import ArtifactAsset, User


router = APIRouter(tags=["产物资源"])


@router.get("/artifact-assets/{asset_id}")
async def get_artifact_asset(
    asset_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(ArtifactAsset, asset_id)
    if not asset or asset.owner_id != user.id:
        raise HTTPException(404, "资源不存在")
    await owned_course(asset.course_id, user, db)
    if asset.status != "approved":
        raise HTTPException(409, "资源尚未通过视觉复核")
    root = get_settings().storage_root.resolve()
    path = (root / asset.relative_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "资源文件不存在")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=path.name,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
