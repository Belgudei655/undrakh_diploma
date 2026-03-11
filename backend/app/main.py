from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    AuthenticatedAdmin,
    AuthenticatedDevice,
    authenticate_admin,
    authenticate_device,
    create_admin_access_token,
    validate_admin_credentials,
)
from app.config import Settings, get_settings
from app.db import get_db, init_db
from app.models import Device
from app.schemas import (
    AdminCreateDeviceRequest,
    AdminCreateDeviceResponse,
    DeviceCommandResponse,
    DeviceRelayUpdateRequest,
    DeviceRelayUpdateResponse,
    DeviceStateResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    DeviceTelemetryRequest,
    DeviceTelemetryResponse,
    LoginRequest,
    LoginResponse,
)
from app.security import hash_device_secret

app = FastAPI(title="ESP32 Backend", version="0.1.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def auth_login(
    payload: LoginRequest,
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    if not validate_admin_credentials(payload.username, payload.password, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token, expires_in = create_admin_access_token(payload.username, settings)
    return LoginResponse(access_token=token, expires_in=expires_in)


@app.post(
    "/api/v1/admin/devices",
    response_model=AdminCreateDeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_device(
    payload: AdminCreateDeviceRequest,
    admin: AuthenticatedAdmin = Depends(authenticate_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> AdminCreateDeviceResponse:
    _ = admin
    existing = (await db.execute(select(Device).where(Device.id == payload.device_id))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already exists")

    now = datetime.now(timezone.utc)
    device = Device(
        id=payload.device_id,
        name=payload.name,
        secret_hash=hash_device_secret(payload.device_secret, settings.device_secret_pepper),
        is_active=True,
        online=False,
        water_detected=False,
        relay_open=False,
        desired_relay_open=False,
        auto_close_on_water_detect=True,
        created_at=now,
        updated_at=now,
    )
    db.add(device)
    await db.commit()

    return AdminCreateDeviceResponse(
        device_id=device.id,
        name=device.name,
        is_active=device.is_active,
        created_at=device.created_at,
    )


@app.get("/api/v1/devices/{device_id}/state", response_model=DeviceStateResponse)
async def get_device_state(
    device_id: str,
    admin: AuthenticatedAdmin = Depends(authenticate_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DeviceStateResponse:
    _ = admin
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    now = datetime.now(timezone.utc)
    online = False
    if device.last_seen_at is not None:
        last_seen_at = device.last_seen_at
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        online = now - last_seen_at <= timedelta(seconds=settings.device_offline_timeout_seconds)

    return DeviceStateResponse(
        device_id=device.id,
        name=device.name,
        is_active=device.is_active,
        online=online,
        last_seen_at=device.last_seen_at,
        firmware_version=device.firmware_version,
        last_ip=device.last_ip,
        last_rssi=device.last_rssi,
        last_water_value=device.last_water_value,
        water_detected=device.water_detected,
        relay_open=device.relay_open,
        desired_relay_open=device.desired_relay_open,
        auto_close_on_water_detect=device.auto_close_on_water_detect,
    )


@app.post("/api/v1/devices/{device_id}/relay", response_model=DeviceRelayUpdateResponse)
async def update_device_relay(
    device_id: str,
    payload: DeviceRelayUpdateRequest,
    admin: AuthenticatedAdmin = Depends(authenticate_admin),
    db: AsyncSession = Depends(get_db),
) -> DeviceRelayUpdateResponse:
    _ = admin
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    if payload.relay_open is not None:
        device.desired_relay_open = payload.relay_open
    if payload.auto_close_on_water_detect is not None:
        device.auto_close_on_water_detect = payload.auto_close_on_water_detect
    if device.auto_close_on_water_detect and device.water_detected:
        device.desired_relay_open = False

    device.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return DeviceRelayUpdateResponse(
        device_id=device.id,
        relay_open=device.relay_open,
        desired_relay_open=device.desired_relay_open,
        auto_close_on_water_detect=device.auto_close_on_water_detect,
    )


@app.post("/api/v1/device/heartbeat", response_model=HeartbeatResponse)
async def device_heartbeat(
    payload: HeartbeatRequest,
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    query = select(Device).where(Device.id == device.device_id)
    device_row = (await db.execute(query)).scalar_one_or_none()

    # Auth dependency guarantees this exists unless deleted between dependency and handler.
    if device_row is not None:
        now = datetime.now(timezone.utc)
        device_row.last_seen_at = now
        device_row.online = True
        device_row.firmware_version = payload.firmware_version or device_row.firmware_version
        device_row.last_ip = payload.ip or device_row.last_ip
        device_row.last_rssi = payload.rssi if payload.rssi is not None else device_row.last_rssi
        device_row.updated_at = now
        await db.commit()

    return HeartbeatResponse(
        ok=True,
        server_time=datetime.now(timezone.utc),
        poll_interval_ms=settings.heartbeat_poll_interval_ms,
    )


@app.post("/api/v1/device/telemetry", response_model=DeviceTelemetryResponse)
async def device_telemetry(
    payload: DeviceTelemetryRequest,
    device: AuthenticatedDevice = Depends(authenticate_device),
    db: AsyncSession = Depends(get_db),
) -> DeviceTelemetryResponse:
    query = select(Device).where(Device.id == device.device_id)
    device_row = (await db.execute(query)).scalar_one_or_none()

    if device_row is not None:
        now = datetime.now(timezone.utc)
        device_row.last_water_value = payload.water_value if payload.water_value is not None else device_row.last_water_value
        if payload.water_detected is not None:
            device_row.water_detected = payload.water_detected
        if payload.relay_open is not None:
            device_row.relay_open = payload.relay_open
        if device_row.auto_close_on_water_detect and device_row.water_detected:
            device_row.desired_relay_open = False
        device_row.updated_at = now
        await db.commit()

    return DeviceTelemetryResponse(
        accepted=True,
        server_time=datetime.now(timezone.utc),
    )


@app.get("/api/v1/device/command", response_model=DeviceCommandResponse)
async def device_command(
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DeviceCommandResponse:
    query = select(Device).where(Device.id == device.device_id)
    device_row = (await db.execute(query)).scalar_one_or_none()

    desired_relay_open = False
    auto_close_on_water_detect = True
    if device_row is not None:
        desired_relay_open = device_row.desired_relay_open
        auto_close_on_water_detect = device_row.auto_close_on_water_detect
        if auto_close_on_water_detect and device_row.water_detected:
            desired_relay_open = False

    return DeviceCommandResponse(
        desired_relay_open=desired_relay_open,
        auto_close_on_water_detect=auto_close_on_water_detect,
        poll_interval_ms=settings.heartbeat_poll_interval_ms,
        server_time=datetime.now(timezone.utc),
    )
