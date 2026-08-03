from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models.entities import User
from app.services.ppt_template_service import load_ppt_template_catalog


router = APIRouter(tags=["PPT 模板"])


@router.get("/ppt-templates")
async def get_ppt_templates(_: User = Depends(current_user)):
    return load_ppt_template_catalog()
