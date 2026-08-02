from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hasher.verify(password, hashed)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return str(payload["sub"])
    except (jwt.PyJWTError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc


def create_stream_token(user_id: str, run_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "run_id": run_id, "type": "sse", "iat": now, "exp": now + timedelta(minutes=5)},
        get_settings().secret_key,
        algorithm="HS256",
    )


def decode_stream_token(token: str, run_id: str) -> str:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("type") != "sse" or payload.get("run_id") != run_id:
            raise ValueError("invalid stream scope")
        return str(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="事件流令牌无效") from exc


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret_key.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode() if value else ""
    except InvalidToken as exc:
        raise RuntimeError("模型密钥无法解密，请重新配置") from exc
