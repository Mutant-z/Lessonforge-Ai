from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import User
from app.schemas.course import Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    identity_filter = User.username == payload.username
    if payload.email:
        identity_filter = or_(identity_filter, User.email == payload.email)
    existing = await db.scalar(select(User).where(identity_filter))
    if existing:
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    user = User(username=payload.username, email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    remember_me: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(or_(User.username == form.username, User.email == form.username)))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    
    is_remember = True if remember_me is None or remember_me == "" else str(remember_me).lower() not in ("false", "0", "no", "off")
    settings = get_settings()
    expire_minutes = (
        settings.access_token_expire_minutes
        if is_remember
        else settings.access_token_expire_minutes_session
    )
    expires_delta = timedelta(minutes=expire_minutes)
    return Token(access_token=create_access_token(user.id, expires_delta=expires_delta))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(current_user)):
    return user
