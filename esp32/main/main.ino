#include <WiFi.h>
#include <HTTPClient.h>

// WiFi
const char* ssid = "";
const char* password = "";

// Backend
const char* heartbeatUrl = "http://192.168.1.11:8000/api/v1/device/heartbeat";
const char* telemetryUrl = "http://192.168.1.11:8000/api/v1/device/telemetry";
const char* commandUrl = "http://192.168.1.11:8000/api/v1/device/command";
const char* deviceId = "esp32-water-001";
const char* deviceSecret = "super-secret-from-firmware";
const char* firmwareVersion = "1.0.0";

// Hardware
const int sensorPowerPin = 4;
const int sensorPin = 34;
const int relayPin = 26;

// Relay behavior
const bool relayNormallyOpen = true;
const int waterDetectedThreshold = 500;

// Timing
unsigned long lastHeartbeatAt = 0;
unsigned long lastTelemetryAt = 0;
unsigned long lastCommandPollAt = 0;
unsigned long lastSensorPrintAt = 0;
unsigned long heartbeatIntervalMs = 5000;
unsigned long telemetryIntervalMs = 500;
unsigned long commandPollIntervalMs = 2000;
const unsigned long sensorPrintIntervalMs = 2000;

int lastWaterValue = 0;
bool relayOpen = false;
bool desiredRelayOpen = false;
bool autoCloseOnWaterDetect = true;

void setRelayOpen(bool openValve) {
  // Relay modules often use inverted logic.
  // For normally-open wiring:
  // LOW  -> current flows
  // HIGH -> current stops
  int signal;

  if (relayNormallyOpen) {
    signal = openValve ? LOW : HIGH;
  } else {
    signal = openValve ? HIGH : LOW;
  }

  digitalWrite(relayPin, signal);
  relayOpen = openValve;

  Serial.print("Relay state: ");
  Serial.println(openValve ? "OPEN" : "CLOSED");
}

int readWaterSensor() {
  digitalWrite(sensorPowerPin, HIGH);
  delay(10);
  int value = analogRead(sensorPin);
  digitalWrite(sensorPowerPin, LOW);
  return value;
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  Serial.print("Connecting to WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");

    if (millis() - startedAt > 20000) {
      Serial.println("\nWiFi connect timeout, retrying...");
      WiFi.disconnect(true, true);
      delay(1000);
      WiFi.begin(ssid, password);
      startedAt = millis();
    }
  }

  Serial.println();
  Serial.print("Connected. ESP32 IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("RSSI: ");
  Serial.println(WiFi.RSSI());
}

bool isWaterDetected(int waterValue) {
  return waterValue >= waterDetectedThreshold;
}

bool extractBoolField(const String& response, const String& key, bool fallback) {
  int keyIndex = response.indexOf(key);
  if (keyIndex < 0) {
    return fallback;
  }

  int valueStart = keyIndex + key.length();
  while (valueStart < response.length() && response.charAt(valueStart) == ' ') {
    valueStart++;
  }

  if (response.startsWith("true", valueStart)) {
    return true;
  }
  if (response.startsWith("false", valueStart)) {
    return false;
  }

  return fallback;
}

void updatePollInterval(const String& response) {
  const String key = "\"poll_interval_ms\":";
  int keyIndex = response.indexOf(key);
  if (keyIndex < 0) {
    return;
  }

  int valueStart = keyIndex + key.length();
  int valueEnd = response.indexOf(",", valueStart);
  if (valueEnd < 0) {
    valueEnd = response.indexOf("}", valueStart);
  }
  if (valueEnd < 0) {
    return;
  }

  String value = response.substring(valueStart, valueEnd);
  value.trim();
  unsigned long parsed = value.toInt();

  if (parsed >= 1000) {
    heartbeatIntervalMs = parsed;
    commandPollIntervalMs = parsed;
    Serial.print("Updated heartbeat interval from server: ");
    Serial.println(heartbeatIntervalMs);
  }
}

void applyServerRelayPolicy(int waterValue) {
  bool waterDetected = isWaterDetected(waterValue);

  if (autoCloseOnWaterDetect && waterDetected) {
    desiredRelayOpen = false;
  }

  if (relayOpen != desiredRelayOpen) {
    setRelayOpen(desiredRelayOpen);
  }
}

void updateRelaySettingsFromResponse(const String& response) {
  desiredRelayOpen = extractBoolField(response, "\"desired_relay_open\":", desiredRelayOpen);
  autoCloseOnWaterDetect =
      extractBoolField(response, "\"auto_close_on_water_detect\":", autoCloseOnWaterDetect);

  Serial.print("Desired relay from server: ");
  Serial.println(desiredRelayOpen ? "OPEN" : "CLOSED");
  Serial.print("Auto close on water detect: ");
  Serial.println(autoCloseOnWaterDetect ? "ENABLED" : "DISABLED");
}

void addCommonHeaders(HTTPClient& http) {
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", deviceId);
  http.addHeader("X-Device-Secret", deviceSecret);
}

void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skipping heartbeat: WiFi disconnected");
    return;
  }

  HTTPClient http;
  http.begin(heartbeatUrl);
  addCommonHeaders(http);

  String payload = "{";
  payload += "\"firmware_version\":\"" + String(firmwareVersion) + "\",";
  payload += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  payload += "\"rssi\":" + String(WiFi.RSSI());
  payload += "}";

  int statusCode = http.POST(payload);

  Serial.print("Heartbeat HTTP code: ");
  Serial.println(statusCode);
  Serial.print("Heartbeat payload: ");
  Serial.println(payload);

  if (statusCode > 0) {
    String response = http.getString();
    Serial.print("Heartbeat response: ");
    Serial.println(response);
    updatePollInterval(response);
  } else {
    Serial.print("Heartbeat failed: ");
    Serial.println(http.errorToString(statusCode));
  }

  http.end();
}

void sendTelemetry(int waterValue) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skipping telemetry: WiFi disconnected");
    return;
  }

  HTTPClient http;
  http.begin(telemetryUrl);
  addCommonHeaders(http);

  String payload = "{";
  payload += "\"water_value\":" + String(waterValue) + ",";
  payload += "\"water_detected\":" + String(isWaterDetected(waterValue) ? "true" : "false") + ",";
  payload += "\"relay_open\":" + String(relayOpen ? "true" : "false");
  payload += "}";

  int statusCode = http.POST(payload);

  Serial.print("Telemetry HTTP code: ");
  Serial.println(statusCode);
  Serial.print("Telemetry payload: ");
  Serial.println(payload);

  if (statusCode > 0) {
    String response = http.getString();
    Serial.print("Telemetry response: ");
    Serial.println(response);
  } else {
    Serial.print("Telemetry failed: ");
    Serial.println(http.errorToString(statusCode));
  }

  http.end();
}

void fetchCommand(int waterValue) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skipping command poll: WiFi disconnected");
    return;
  }

  HTTPClient http;
  http.begin(commandUrl);
  http.addHeader("X-Device-Id", deviceId);
  http.addHeader("X-Device-Secret", deviceSecret);

  int statusCode = http.GET();

  Serial.print("Command HTTP code: ");
  Serial.println(statusCode);

  if (statusCode > 0) {
    String response = http.getString();
    Serial.print("Command response: ");
    Serial.println(response);
    updatePollInterval(response);
    updateRelaySettingsFromResponse(response);
    applyServerRelayPolicy(waterValue);
  } else {
    Serial.print("Command poll failed: ");
    Serial.println(http.errorToString(statusCode));
  }

  http.end();
}

void printSensorStatus(int waterValue) {
  Serial.print("Water level: ");
  Serial.print(waterValue);
  Serial.print(" | Water detected: ");
  Serial.print(isWaterDetected(waterValue) ? "yes" : "no");
  Serial.print(" | Relay: ");
  Serial.print(relayOpen ? "open" : "closed");
  Serial.print(" | RSSI: ");
  Serial.print(WiFi.RSSI());
  Serial.print(" | WiFi: ");
  Serial.println(WiFi.status() == WL_CONNECTED ? "connected" : "disconnected");
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(sensorPowerPin, OUTPUT);
  digitalWrite(sensorPowerPin, LOW);

  pinMode(relayPin, OUTPUT);
  setRelayOpen(false);
  desiredRelayOpen = false;

  connectWifi();
}

void loop() {
  connectWifi();

  lastWaterValue = readWaterSensor();
  applyServerRelayPolicy(lastWaterValue);

  unsigned long now = millis();

  if (now - lastSensorPrintAt >= sensorPrintIntervalMs) {
    printSensorStatus(lastWaterValue);
    lastSensorPrintAt = now;
  }

  if (now - lastHeartbeatAt >= heartbeatIntervalMs) {
    sendHeartbeat();
    lastHeartbeatAt = now;
  }

  if (now - lastTelemetryAt >= telemetryIntervalMs) {
    sendTelemetry(lastWaterValue);
    lastTelemetryAt = now;
  }

  if (now - lastCommandPollAt >= commandPollIntervalMs) {
    fetchCommand(lastWaterValue);
    lastCommandPollAt = now;
  }

  delay(100);
}
