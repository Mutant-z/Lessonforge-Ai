from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()

# 历史遗留默认密钥：用于兼容在切换 SECRET_KEY 之前签发的旧 Token 与已加密的模型密钥。
# 新 Token 一律使用当前 secret_key 签发/加密；校验与解密时按顺序尝试，保证平滑迁移。
LEGACY_SECRET_KEY = "development-only-change-this-secret-key"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(password, hashed)
    except UnknownHashError:
        # 数据库中的历史脏数据可能不是合法哈希（如测试写入的 "hash"），
        # 校验失败按密码错误处理，而不是抛 500。
        return False


def _signing_keys() -> list[str]:
    """当前密钥优先，历史遗留密钥兜底，避免密钥切换后旧会话与旧密文失效。"""
    settings = get_settings()
    keys = [settings.secret_key]
    if settings.secret_key != LEGACY_SECRET_KEY:
        keys.append(LEGACY_SECRET_KEY)
    return keys


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta if expires_delta is not None else timedelta(minutes=settings.access_token_expire_minutes))
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> str:
    last_exc: Exception | None = None
    for key in _signing_keys():
        try:
            payload = jwt.decode(token, key, algorithms=["HS256"])
            return str(payload["sub"])
        except (jwt.PyJWTError, KeyError) as exc:
            last_exc = exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from last_exc


def create_stream_token(user_id: str, run_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "run_id": run_id, "type": "sse", "iat": now, "exp": now + timedelta(minutes=5)},
        get_settings().secret_key,
        algorithm="HS256",
    )


def decode_stream_token(token: str, run_id: str) -> str:
    last_exc: Exception | None = None
    for key in _signing_keys():
        try:
            payload = jwt.decode(token, key, algorithms=["HS256"])
            if payload.get("type") != "sse" or payload.get("run_id") != run_id:
                raise ValueError("invalid stream scope")
            return str(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            last_exc = exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="事件流令牌无效") from last_exc


def create_asset_token(user_id: str, asset_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "asset_id": asset_id, "type": "asset", "iat": now, "exp": now + timedelta(minutes=15)},
        get_settings().secret_key,
        algorithm="HS256",
    )


def decode_asset_token(token: str, asset_id: str) -> str:
    last_exc: Exception | None = None
    for key in _signing_keys():
        try:
            payload = jwt.decode(token, key, algorithms=["HS256"])
            if payload.get("type") != "asset" or payload.get("asset_id") != asset_id:
                raise ValueError("invalid asset scope")
            return str(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            last_exc = exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="媒体访问令牌无效") from last_exc


def _fernet(key: str) -> Fernet:
    material = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(material)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet(get_settings().secret_key).encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    last_exc: Exception | None = None
    for key in _signing_keys():
        try:
            return _fernet(key).decrypt(value.encode()).decode()
        except InvalidToken as exc:
            last_exc = exc
    raise RuntimeError("模型密钥无法解密，请重新配置") from last_exc
