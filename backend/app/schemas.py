from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    firmware_version: str | None = Field(default=None, max_length=64)
    ip: str | None = Field(default=None, max_length=64)
    rssi: int | None = None
    ts: datetime | None = None


class DeviceTelemetryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    water_value: int | None = None
    water_detected: bool | None = None
    relay_open: bool | None = None
    ts: datetime | None = None


class HeartbeatResponse(BaseModel):
    ok: bool
    server_time: datetime
    poll_interval_ms: int


class DeviceTelemetryResponse(BaseModel):
    accepted: bool
    server_time: datetime


class CommandSummary(BaseModel):
    command_id: str
    action: str
    desired_relay_open: bool
    status: str
    created_at: datetime
    delivered_at: datetime | None
    acked_at: datetime | None
    error_code: str | None


class DeviceCommandResponse(BaseModel):
    command_id: str | None = None
    command_status: str | None = None
    desired_relay_open: bool
    auto_close_on_water_detect: bool
    poll_interval_ms: int
    server_time: datetime


class AdminCreateDeviceRequest(BaseModel):
    device_id: str = Field(min_length=3, max_length=64)
    device_secret: str = Field(min_length=8, max_length=256)
    name: str | None = Field(default=None, max_length=128)


class AdminCreateDeviceResponse(BaseModel):
    device_id: str
    name: str | None
    is_active: bool
    created_at: datetime


class DeviceStateResponse(BaseModel):
    device_id: str
    name: str | None
    is_active: bool
    online: bool
    last_seen_at: datetime | None
    firmware_version: str | None
    last_ip: str | None
    last_rssi: int | None
    last_water_value: int | None
    water_detected: bool
    relay_open: bool
    desired_relay_open: bool
    auto_close_on_water_detect: bool
    latest_command: CommandSummary | None = None


class DeviceRelayUpdateRequest(BaseModel):
    relay_open: bool | None = None
    auto_close_on_water_detect: bool | None = None


class DeviceRelayUpdateResponse(BaseModel):
    device_id: str
    relay_open: bool
    desired_relay_open: bool
    auto_close_on_water_detect: bool
    latest_command: CommandSummary | None = None


class DeviceCommandAckRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=64)
    result: str = Field(pattern="^(ok|error)$")
    relay_open: bool | None = None
    error_code: str | None = Field(default=None, max_length=64)


class DeviceCommandAckResponse(BaseModel):
    ok: bool
    command_id: str
    status: str
    acked_at: datetime | None
    error_code: str | None
