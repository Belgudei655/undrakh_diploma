import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    AuthenticatedAdmin,
    AuthenticatedDevice,
    authenticate_admin,
    authenticate_admin_token,
    authenticate_device,
    create_admin_access_token,
    validate_admin_credentials,
)
from app.config import Settings, get_settings
from app.db import SessionLocal, get_db, init_db
from app.events import event_broker
from app.models import Command, Device
from app.schemas import (
    AdminCreateDeviceRequest,
    AdminCreateDeviceResponse,
    CommandSummary,
    DeviceCommandAckRequest,
    DeviceCommandAckResponse,
    DeviceCommandResponse,
    DeviceRelayUpdateRequest,
    DeviceRelayUpdateResponse,
    DeviceStateResponse,
    DeviceTelemetryRequest,
    DeviceTelemetryResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LoginRequest,
    LoginResponse,
)
from app.security import hash_device_secret

app = FastAPI(title="ESP32 Backend", version="0.2.0")
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_device_online(device: Device, settings: Settings, now: datetime | None = None) -> bool:
    if device.last_seen_at is None:
        return False
    current_time = now or datetime.now(timezone.utc)
    return current_time - _as_utc(device.last_seen_at) <= timedelta(seconds=settings.device_offline_timeout_seconds)


def serialize_command(command: Command | None) -> CommandSummary | None:
    if command is None:
        return None

    return CommandSummary(
        command_id=command.id,
        action=command.action,
        desired_relay_open=command.desired_relay_open,
        status=command.status,
        created_at=command.created_at,
        delivered_at=command.delivered_at,
        acked_at=command.acked_at,
        error_code=command.error_code,
    )


def build_device_state_response(
    device: Device,
    settings: Settings,
    latest_command: Command | None = None,
) -> DeviceStateResponse:
    return DeviceStateResponse(
        device_id=device.id,
        name=device.name,
        is_active=device.is_active,
        online=is_device_online(device, settings),
        last_seen_at=device.last_seen_at,
        firmware_version=device.firmware_version,
        last_ip=device.last_ip,
        last_rssi=device.last_rssi,
        last_water_value=device.last_water_value,
        water_detected=device.water_detected,
        relay_open=device.relay_open,
        desired_relay_open=device.desired_relay_open,
        auto_close_on_water_detect=device.auto_close_on_water_detect,
        latest_command=serialize_command(latest_command),
    )


async def get_device_or_404(db: AsyncSession, device_id: str) -> Device:
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def get_latest_command(db: AsyncSession, device_id: str) -> Command | None:
    query = select(Command).where(Command.device_id == device_id).order_by(Command.created_at.desc())
    return (await db.execute(query)).scalars().first()


async def get_outstanding_command(db: AsyncSession, device_id: str) -> Command | None:
    query = (
        select(Command)
        .where(Command.device_id == device_id, Command.status.in_(("pending", "delivered")))
        .order_by(Command.created_at.desc())
    )
    return (await db.execute(query)).scalars().first()


async def expire_outstanding_commands(db: AsyncSession, device_id: str, now: datetime) -> None:
    query = (
        select(Command)
        .where(Command.device_id == device_id, Command.status.in_(("pending", "delivered")))
        .order_by(Command.created_at.desc())
    )
    for command in (await db.execute(query)).scalars().all():
        command.status = "expired"
        command.error_code = "SUPERSEDED"
        command.updated_at = now


def publish_command_update(device_id: str, command: Command | None) -> None:
    payload = serialize_command(command)
    if payload is None:
        return
    event_broker.publish(device_id, "command.updated", payload.model_dump(mode="json"))


def publish_device_snapshot(device: Device, settings: Settings, latest_command: Command | None) -> None:
    snapshot = build_device_state_response(device, settings, latest_command).model_dump(mode="json")
    event_broker.publish(device.id, "device.snapshot", snapshot)


async def load_device_snapshot(device_id: str, settings: Settings) -> DeviceStateResponse | None:
    async with SessionLocal() as db:
        device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
        if device is None:
            return None
        latest_command = await get_latest_command(db, device_id)
        return build_device_state_response(device, settings, latest_command)


def format_sse_event(event_type: str, data: object, retry_ms: int = 3000) -> str:
    lines = [f"retry: {retry_ms}", f"event: {event_type}"]
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    for line in payload.splitlines() or ("{}",):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


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

    publish_device_snapshot(device, settings, None)

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
    device = await get_device_or_404(db, device_id)
    latest_command = await get_latest_command(db, device_id)
    return build_device_state_response(device, settings, latest_command)


@app.get("/api/v1/devices/{device_id}/events")
async def stream_device_events(
    device_id: str,
    request: Request,
    token: str = Query(min_length=1),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    _ = authenticate_admin_token(token, settings)
    await get_device_or_404(db, device_id)

    async def event_stream():
        subscriber = event_broker.subscribe(device_id)
        try:
            initial_snapshot = await load_device_snapshot(device_id, settings)
            if initial_snapshot is not None:
                yield format_sse_event("device.snapshot", initial_snapshot.model_dump(mode="json"))

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(subscriber.get(), timeout=settings.sse_snapshot_interval_seconds)
                    yield format_sse_event(str(event["type"]), event["data"])
                except asyncio.TimeoutError:
                    snapshot = await load_device_snapshot(device_id, settings)
                    if snapshot is None:
                        yield format_sse_event("device.deleted", {"device_id": device_id})
                        break
                    yield format_sse_event("device.snapshot", snapshot.model_dump(mode="json"))
        finally:
            event_broker.unsubscribe(device_id, subscriber)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.post("/api/v1/devices/{device_id}/relay", response_model=DeviceRelayUpdateResponse)
async def update_device_relay(
    device_id: str,
    payload: DeviceRelayUpdateRequest,
    admin: AuthenticatedAdmin = Depends(authenticate_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DeviceRelayUpdateResponse:
    _ = admin
    device = await get_device_or_404(db, device_id)
    now = datetime.now(timezone.utc)

    if payload.auto_close_on_water_detect is not None:
        device.auto_close_on_water_detect = payload.auto_close_on_water_detect
    if payload.relay_open is not None:
        await expire_outstanding_commands(db, device_id, now)
        device.desired_relay_open = payload.relay_open
    if device.auto_close_on_water_detect and device.water_detected:
        device.desired_relay_open = False

    new_command = None
    if payload.relay_open is not None:
        new_command = Command(
            id=str(uuid4()),
            device_id=device_id,
            action="set_relay",
            desired_relay_open=device.desired_relay_open,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(new_command)

    device.updated_at = now
    await db.commit()

    latest_command = new_command or await get_latest_command(db, device_id)
    if new_command is not None:
        publish_command_update(device_id, new_command)
    publish_device_snapshot(device, settings, latest_command)

    return DeviceRelayUpdateResponse(
        device_id=device.id,
        relay_open=device.relay_open,
        desired_relay_open=device.desired_relay_open,
        auto_close_on_water_detect=device.auto_close_on_water_detect,
        latest_command=serialize_command(latest_command),
    )


@app.post("/api/v1/device/heartbeat", response_model=HeartbeatResponse)
async def device_heartbeat(
    payload: HeartbeatRequest,
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    device_row = (await db.execute(select(Device).where(Device.id == device.device_id))).scalar_one_or_none()

    if device_row is not None:
        now = datetime.now(timezone.utc)
        was_online = is_device_online(device_row, settings, now)
        device_row.last_seen_at = now
        device_row.online = True
        device_row.firmware_version = payload.firmware_version or device_row.firmware_version
        device_row.last_ip = payload.ip or device_row.last_ip
        device_row.last_rssi = payload.rssi if payload.rssi is not None else device_row.last_rssi
        device_row.updated_at = now
        await db.commit()

        latest_command = await get_latest_command(db, device.device_id)
        if not was_online:
            event_broker.publish(device.device_id, "device.online", {"device_id": device.device_id, "server_time": now.isoformat()})
        publish_device_snapshot(device_row, settings, latest_command)

    return HeartbeatResponse(
        ok=True,
        server_time=datetime.now(timezone.utc),
        poll_interval_ms=settings.heartbeat_poll_interval_ms,
    )


@app.post("/api/v1/device/telemetry", response_model=DeviceTelemetryResponse)
async def device_telemetry(
    payload: DeviceTelemetryRequest,
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DeviceTelemetryResponse:
    device_row = (await db.execute(select(Device).where(Device.id == device.device_id))).scalar_one_or_none()

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

        latest_command = await get_latest_command(db, device.device_id)
        event_broker.publish(
            device.device_id,
            "telemetry.updated",
            {
                "device_id": device.device_id,
                "water_value": device_row.last_water_value,
                "water_detected": device_row.water_detected,
                "relay_open": device_row.relay_open,
                "server_time": now.isoformat(),
            },
        )
        publish_device_snapshot(device_row, settings, latest_command)

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
    device_row = (await db.execute(select(Device).where(Device.id == device.device_id))).scalar_one_or_none()
    outstanding_command = await get_outstanding_command(db, device.device_id)

    desired_relay_open = False
    auto_close_on_water_detect = True
    if device_row is not None:
        desired_relay_open = device_row.desired_relay_open
        auto_close_on_water_detect = device_row.auto_close_on_water_detect
        if auto_close_on_water_detect and device_row.water_detected:
            desired_relay_open = False

    if outstanding_command is not None and outstanding_command.status == "pending":
        outstanding_command.status = "delivered"
        outstanding_command.delivered_at = datetime.now(timezone.utc)
        outstanding_command.updated_at = outstanding_command.delivered_at
        await db.commit()
        publish_command_update(device.device_id, outstanding_command)
        if device_row is not None:
            publish_device_snapshot(device_row, settings, outstanding_command)

    poll_interval_ms = settings.command_poll_interval_ms if outstanding_command is not None else settings.command_poll_idle_interval_ms

    return DeviceCommandResponse(
        command_id=outstanding_command.id if outstanding_command is not None else None,
        command_status=outstanding_command.status if outstanding_command is not None else None,
        desired_relay_open=desired_relay_open,
        auto_close_on_water_detect=auto_close_on_water_detect,
        poll_interval_ms=poll_interval_ms,
        server_time=datetime.now(timezone.utc),
    )


@app.post("/api/v1/device/command-ack", response_model=DeviceCommandAckResponse)
async def device_command_ack(
    payload: DeviceCommandAckRequest,
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DeviceCommandAckResponse:
    command = (
        await db.execute(select(Command).where(Command.id == payload.command_id, Command.device_id == device.device_id))
    ).scalar_one_or_none()
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")

    if command.status in {"acked", "failed", "expired"}:
        return DeviceCommandAckResponse(
            ok=True,
            command_id=command.id,
            status=command.status,
            acked_at=command.acked_at,
            error_code=command.error_code,
        )

    now = datetime.now(timezone.utc)
    device_row = (await db.execute(select(Device).where(Device.id == device.device_id))).scalar_one_or_none()

    if payload.result == "ok":
        command.status = "acked"
        command.acked_at = now
        command.error_code = None
        if device_row is not None and payload.relay_open is not None:
            device_row.relay_open = payload.relay_open
    else:
        command.status = "failed"
        command.error_code = payload.error_code or "DEVICE_ERROR"

    command.updated_at = now
    if device_row is not None:
        device_row.updated_at = now

    await db.commit()

    publish_command_update(device.device_id, command)
    if device_row is not None:
        publish_device_snapshot(device_row, settings, command)

    return DeviceCommandAckResponse(
        ok=True,
        command_id=command.id,
        status=command.status,
        acked_at=command.acked_at,
        error_code=command.error_code,
    )
