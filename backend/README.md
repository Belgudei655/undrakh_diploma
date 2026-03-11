# Backend (JWT Admin Auth + ESP32 Telemetry + Relay Control)

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 1) Login to get JWT
`POST /api/v1/auth/login`

Example:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

Response returns `access_token`.

## 2) Create Device (admin JWT required)
`POST /api/v1/admin/devices`

Example:
```bash
TOKEN="<paste-access-token>"

curl -X POST "http://localhost:8000/api/v1/admin/devices" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"esp32-water-001","device_secret":"super-secret-from-firmware","name":"greenhouse-valve-1"}'
```

## 3) Get Device State (admin JWT required)
`GET /api/v1/devices/{device_id}/state`

Example:
```bash
TOKEN="<paste-access-token>"

curl -X GET "http://localhost:8000/api/v1/devices/esp32-water-001/state" \
  -H "Authorization: Bearer ${TOKEN}"
```

Example response:
```json
{
  "device_id": "esp32-water-001",
  "name": "greenhouse-valve-1",
  "is_active": true,
  "online": true,
  "last_seen_at": "2026-03-11T10:15:02Z",
  "firmware_version": "1.0.0",
  "last_ip": "192.168.1.110",
  "last_rssi": -59,
  "last_water_value": 2087,
  "water_detected": true,
  "relay_open": false,
  "desired_relay_open": false,
  "auto_close_on_water_detect": true
}
```

## 4) Update Relay Settings (admin JWT required)
`POST /api/v1/devices/{device_id}/relay`

Use this endpoint from the website to open/close the relay or enable/disable automatic close when water is detected.

Example:
```bash
TOKEN="<paste-access-token>"

curl -X POST "http://localhost:8000/api/v1/devices/esp32-water-001/relay" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"relay_open":true,"auto_close_on_water_detect":false}'
```

Example response:
```json
{
  "device_id": "esp32-water-001",
  "relay_open": false,
  "desired_relay_open": true,
  "auto_close_on_water_detect": false
}
```

## 5) ESP32 Heartbeat
Purpose:
- Keep the device marked online
- Refresh firmware, IP, and RSSI metadata

Example:
```bash
curl -X POST "http://localhost:8000/api/v1/device/heartbeat" \
  -H "Content-Type: application/json" \
  -H "X-Device-Id: esp32-water-001" \
  -H "X-Device-Secret: super-secret-from-firmware" \
  -d '{"firmware_version":"1.0.0","rssi":-62,"ip":"203.0.113.15"}'
```

Example response:
```json
{
  "ok": true,
  "server_time": "2026-03-11T10:15:02Z",
  "poll_interval_ms": 1000
}
```

## 6) ESP32 Telemetry
Purpose:
- Report water sensor readings
- Report current relay state

Example:
```bash
curl -X POST "http://localhost:8000/api/v1/device/telemetry" \
  -H "Content-Type: application/json" \
  -H "X-Device-Id: esp32-water-001" \
  -H "X-Device-Secret: super-secret-from-firmware" \
  -d '{"water_value":2087,"water_detected":true,"relay_open":false}'
```

Example response:
```json
{
  "accepted": true,
  "server_time": "2026-03-11T10:15:05Z"
}
```

## 7) ESP32 Command Poll
Purpose:
- Let the ESP32 fetch the latest backend command/config
- Keep relay control and auto-close behavior separate from telemetry

Example:
```bash
curl -X GET "http://localhost:8000/api/v1/device/command" \
  -H "X-Device-Id: esp32-water-001" \
  -H "X-Device-Secret: super-secret-from-firmware"
```

Example response:
```json
{
  "desired_relay_open": false,
  "auto_close_on_water_detect": true,
  "poll_interval_ms": 1000,
  "server_time": "2026-03-11T10:15:06Z"
}
```

## Notes
- `online` is computed from `last_seen_at` and `DEVICE_OFFLINE_TIMEOUT_SECONDS`.
- If `auto_close_on_water_detect` is enabled and the device reports water detected, the backend forces `desired_relay_open` to `false`.
- The frontend should never talk to the ESP32 directly. It reads backend-computed device state and sends relay changes to the backend only.
