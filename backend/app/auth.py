from datetime import datetime, timedelta, timezone
from hmac import compare_digest

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Device
from app.security import verify_device_secret

bearer_auth = HTTPBearer(auto_error=False)


class AuthenticatedDevice(BaseModel):
    device_id: str


class AuthenticatedAdmin(BaseModel):
    username: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _admin_unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing admin token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_admin_credentials(username: str, password: str, settings: Settings) -> bool:
    valid_username = compare_digest(username, settings.admin_username)
    valid_password = compare_digest(password, settings.admin_password)
    return valid_username and valid_password


def create_admin_access_token(username: str, settings: Settings) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.jwt_exp_minutes)
    exp = now + expires_delta
    payload = {
        "sub": username,
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def authenticate_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedAdmin:
    if credentials is None:
        raise _admin_unauthorized()

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise _admin_unauthorized() from exc

    username = payload.get("sub")
    role = payload.get("role")
    if not isinstance(username, str) or role != "admin":
        raise _admin_unauthorized()

    return AuthenticatedAdmin(username=username)


async def authenticate_device(
    device_id: str | None = Header(default=None, alias="X-Device-Id"),
    device_secret: str | None = Header(default=None, alias="X-Device-Secret"),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedDevice:
    if not device_id or not device_secret:
        raise _unauthorized("Missing device credentials")

    query = select(Device).where(Device.id == device_id)
    device = (await db.execute(query)).scalar_one_or_none()

    if device is None:
        raise _unauthorized("Invalid device credentials")

    if not device.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device is disabled")

    if not verify_device_secret(device_secret, device.secret_hash, settings.device_secret_pepper):
        raise _unauthorized("Invalid device credentials")

    return AuthenticatedDevice(device_id=device_id)
