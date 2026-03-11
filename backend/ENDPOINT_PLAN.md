# FastAPI HTTP-Only Endpoint Plan

## Scope
Small IoT backend for one or a few ESP32 devices with:
- Water sensor telemetry
- Relay/valve control
- Frontend dashboard and control
- SQLite persistence

## Tech Assumptions
- FastAPI
- SQLite (single instance backend)
- SQLAlchemy + Alembic (or equivalent migration tool)
- JWT auth for frontend users
- Header auth for device-to-backend calls

## Conventions
- Base path: `/api/v1`
- Timestamps: ISO-8601 UTC (example: `2026-03-11T10:15:00Z`)
- IDs: UUID strings
- Valve actions: `open`, `close`
- Command statuses: `pending`, `delivered`, `acked`, `failed`, `expired`

## Authentication

### Device Authentication
Required for all `/device/*` endpoints:
- `X-Device-Id: <device_id>`
- `X-Device-Secret: <device_secret>`

Validation logic:
- Missing headers -> `401`
- Invalid credentials -> `401`
- Disabled device -> `403`

### User Authentication
Required for all frontend/admin endpoints (except login):
- `Authorization: Bearer <jwt>`

Validation logic:
- Missing token -> `401`
- Invalid/expired token -> `401`
- Insufficient role (if RBAC later) -> `403`

## Device Endpoints (ESP32)

## 1) POST `/api/v1/device/heartbeat`
Purpose:
- Keep device marked online
- Update last seen timestamp

Auth:
- Device headers required

Request body:
```json
{
  "firmware_version": "1.0.0",
  "ip": "203.0.113.5",
  "rssi": -64,
  "ts": "2026-03-11T10:15:00Z"
}
```

Logic:
1. Authenticate device
2. Update `devices.last_seen_at = now()`
3. Set `devices.online = true`
4. Optionally store firmware/rssi/ip if provided
5. Return recommended polling interval

Response `200`:
```json
{
  "ok": true,
  "server_time": "2026-03-11T10:15:02Z",
  "poll_interval_ms": 1000
}
```

## 2) POST `/api/v1/device/telemetry`
Purpose:
- Receive water sensor readings + current valve state

Auth:
- Device headers required

Request body:
```json
{
  "water_value": 378,
  "water_unit": "raw",
  "valve_state": "open",
  "battery": 3.92,
  "ts": "2026-03-11T10:15:00Z"
}
```

Validation:
- `water_value` required and within configured range
- `valve_state` in `open|close` (or `opened|closed`, choose one canonical set)
- `ts` parseable timestamp

Logic:
1. Authenticate device
2. Insert reading into `sensor_readings`
3. Update `devices.last_water_value`, `devices.last_valve_state`, `devices.last_seen_at`
4. Optional: trigger threshold event if value crosses configured limit
5. Optional: push live event to frontend stream

Response `202`:
```json
{
  "accepted": true
}
```

## 3) GET `/api/v1/device/commands`
Purpose:
- ESP32 polls for next command

Auth:
- Device headers required

Query params:
- `limit` default `1`, max `5`

Logic:
1. Authenticate device
2. Fetch oldest `pending` command(s)
3. Mark returned command(s) as `delivered` and set `delivered_at = now()`
4. Return command list
5. If none, return empty list

Response `200`:
```json
{
  "commands": [
    {
      "command_id": "9d1de9ff-a48d-41ad-ac18-5ab1f7d8fb32",
      "action": "open",
      "created_at": "2026-03-11T10:14:58Z"
    }
  ]
}
```

Idle response `200`:
```json
{
  "commands": []
}
```

## 4) POST `/api/v1/device/command-ack`
Purpose:
- Device acknowledges command execution

Auth:
- Device headers required

Request body:
```json
{
  "command_id": "9d1de9ff-a48d-41ad-ac18-5ab1f7d8fb32",
  "result": "ok",
  "error_code": null,
  "ts": "2026-03-11T10:15:03Z"
}
```

Validation:
- Command exists and belongs to authenticated device
- `result` in `ok|error`

Logic:
1. Authenticate device
2. Load command by `command_id`
3. Ensure device ownership
4. Idempotency: if already terminal (`acked`/`failed`), return success without mutation
5. If `result=ok`: set status `acked`, `acked_at=now()`
6. If `result=error`: set status `failed`, persist `error_code`
7. If success, update `devices.last_valve_state` based on command action
8. Optional: push live event to frontend stream

Response `200`:
```json
{
  "updated": true
}
```

## 5) POST `/api/v1/device/register` (optional)
Purpose:
- First-time provisioning if not pre-created by admin

Auth:
- Provisioning token in body (or remove endpoint and pre-provision in DB)

Request body:
```json
{
  "device_name": "greenhouse-valve-1",
  "provisioning_token": "<token>"
}
```

Logic:
1. Validate provisioning token
2. Create device record and generated device secret
3. Return credentials once

Response `201`:
```json
{
  "device_id": "b70f648d-c3bf-49d0-9c34-e9d7dc6d5d3e",
  "device_secret": "<generated-secret>"
}
```

## Frontend/User Endpoints

## 6) POST `/api/v1/auth/login`
Purpose:
- User login and JWT issue

Request body:
```json
{
  "email": "admin@example.com",
  "password": "strong_password"
}
```

Logic:
1. Validate credentials
2. Issue JWT with expiry

Response `200`:
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

## 7) GET `/api/v1/devices`
Purpose:
- List devices and current snapshot

Auth:
- JWT required

Logic:
1. Fetch all visible devices
2. Include online status and latest values

Response `200`:
```json
[
  {
    "device_id": "b70f648d-c3bf-49d0-9c34-e9d7dc6d5d3e",
    "name": "greenhouse-valve-1",
    "online": true,
    "last_seen_at": "2026-03-11T10:15:02Z",
    "last_water_value": 378,
    "last_valve_state": "open"
  }
]
```

## 8) GET `/api/v1/devices/{device_id}/state`
Purpose:
- Full current state for a single device card/page

Auth:
- JWT required

Logic:
1. Validate device exists
2. Return latest snapshot + pending command count

Response `200`:
```json
{
  "device_id": "b70f648d-c3bf-49d0-9c34-e9d7dc6d5d3e",
  "online": true,
  "last_seen_at": "2026-03-11T10:15:02Z",
  "last_water_value": 378,
  "last_valve_state": "open",
  "pending_command_count": 0
}
```

## 9) GET `/api/v1/devices/{device_id}/telemetry`
Purpose:
- Historical sensor data for chart

Auth:
- JWT required

Query params:
- `from` ISO datetime (optional)
- `to` ISO datetime (optional)
- `limit` default `200`, max `2000`

Logic:
1. Validate range (from <= to)
2. Query `sensor_readings` by device and time range
3. Sort ascending by timestamp

Response `200`:
```json
[
  {
    "water_value": 378,
    "water_unit": "raw",
    "valve_state": "open",
    "ts": "2026-03-11T10:15:00Z"
  }
]
```

## 10) POST `/api/v1/devices/{device_id}/valve`
Purpose:
- Enqueue valve action for ESP32

Auth:
- JWT required

Request body:
```json
{
  "action": "close",
  "idempotency_key": "c78f8b73-65f7-498f-a3d4-2d1f177da840"
}
```

Validation:
- `action` in `open|close`

Logic:
1. Validate device exists
2. Optional conflict policy: if existing `pending` or `delivered` command exists, return `409`
3. If `idempotency_key` duplicates prior request for same device, return existing command
4. Insert command with status `pending`
5. Return command metadata

Response `202`:
```json
{
  "command_id": "9d1de9ff-a48d-41ad-ac18-5ab1f7d8fb32",
  "status": "pending"
}
```

## 11) GET `/api/v1/devices/{device_id}/commands/{command_id}`
Purpose:
- Check command lifecycle from frontend

Auth:
- JWT required

Logic:
1. Validate device + command ownership
2. Return current status and timestamps

Response `200`:
```json
{
  "command_id": "9d1de9ff-a48d-41ad-ac18-5ab1f7d8fb32",
  "action": "close",
  "status": "acked",
  "created_at": "2026-03-11T10:14:58Z",
  "delivered_at": "2026-03-11T10:15:00Z",
  "acked_at": "2026-03-11T10:15:03Z",
  "error_code": null
}
```

## Optional Realtime Endpoint

## 12) GET `/api/v1/devices/{device_id}/events` (SSE) or `WS /api/v1/ws/devices/{device_id}`
Purpose:
- Push telemetry updates, command updates, online/offline changes to frontend

Auth:
- JWT required

Event types:
- `telemetry.updated`
- `command.updated`
- `device.online`
- `device.offline`

## Core Background Logic

## A) Offline Detector Job
Interval:
- Every 10-15 seconds

Logic:
1. Find devices with `now - last_seen_at > offline_timeout` (e.g., 60s)
2. Mark `online=false`
3. Emit offline event (optional)

## B) Command Expiry Job
Interval:
- Every 5 seconds

Logic:
1. Find commands in `pending` or `delivered` older than timeout (e.g., 30-60s)
2. Mark as `expired`
3. Emit command update event (optional)

## C) Telemetry Rate Guard
Logic:
- Per device, reject or coalesce telemetry above configured rate (example: >1 req/sec)
- Return `429` if hard throttled

## D) Idempotency Rules
- `POST /devices/{id}/valve` uses unique (`device_id`, `idempotency_key`)
- `POST /device/command-ack` is idempotent for terminal states

## SQLite Schema (Minimal)

## `devices`
Fields:
- `id` (uuid, pk)
- `name` (text)
- `secret_hash` (text)
- `online` (bool)
- `last_seen_at` (datetime)
- `last_water_value` (real/int)
- `last_valve_state` (text)
- `created_at` (datetime)
- `updated_at` (datetime)

Indexes:
- `idx_devices_last_seen_at`

## `sensor_readings`
Fields:
- `id` (uuid, pk)
- `device_id` (fk devices.id)
- `water_value` (real/int)
- `water_unit` (text)
- `valve_state` (text)
- `battery` (real, nullable)
- `ts` (datetime)
- `created_at` (datetime)

Indexes:
- `idx_sensor_readings_device_ts` on (`device_id`, `ts`)

## `commands`
Fields:
- `id` (uuid, pk)
- `device_id` (fk devices.id)
- `action` (text)
- `status` (text)
- `idempotency_key` (text, nullable)
- `error_code` (text, nullable)
- `created_by_user_id` (fk users.id, nullable)
- `created_at` (datetime)
- `delivered_at` (datetime, nullable)
- `acked_at` (datetime, nullable)
- `expires_at` (datetime, nullable)

Indexes:
- `idx_commands_device_status_created_at` on (`device_id`, `status`, `created_at`)
- unique index on (`device_id`, `idempotency_key`) when key is not null

## `users`
Fields:
- `id` (uuid, pk)
- `email` (text, unique)
- `password_hash` (text)
- `is_active` (bool)
- `created_at` (datetime)

## Error Contract
Use consistent envelope for non-2xx:
```json
{
  "error": {
    "code": "COMMAND_CONFLICT",
    "message": "Another command is still pending",
    "details": null
  }
}
```

Typical statuses:
- `400` validation failure
- `401` unauthorized
- `403` forbidden
- `404` not found
- `409` conflict
- `429` too many requests
- `500` internal server error

## Operational Defaults
- Heartbeat interval: 20s
- Command poll interval: 1s (backoff to 3-5s if idle)
- Telemetry interval: 2-10s
- Offline timeout: 60s
- Command expiry: 45s

## Step-by-Step Implementation Order
1. Define models + migrations (`devices`, `sensor_readings`, `commands`, `users`)
2. Implement device auth dependency
3. Implement `/device/heartbeat`, `/device/telemetry`, `/device/commands`, `/device/command-ack`
4. Implement user auth + `/auth/login`
5. Implement `/devices`, `/devices/{id}/state`, `/devices/{id}/telemetry`
6. Implement `/devices/{id}/valve` and command status endpoint
7. Add background jobs (offline detector + command expiry)
8. Add SSE/WS realtime stream (optional)
9. Add tests for command lifecycle and idempotency
