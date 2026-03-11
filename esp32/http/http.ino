#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid = "Univision_4386";
const char* password = "8db05cf1f7ca";

// Important: the ESP32 cannot use localhost.
// Use your laptop's LAN IPv4 address instead.
const char* serverName = "http://192.168.1.11:8000/api/v1/device/heartbeat";

const char* deviceId = "esp32-water-002";
const char* deviceSecret = "super-secret-from-firmware";
const char* firmwareVersion = "1.0.0";

unsigned long lastTime = 0;
unsigned long timerDelay = 5000;

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.print("Connected. IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  if ((millis() - lastTime) > timerDelay) {
    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;

      http.begin(serverName);
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Device-Id", deviceId);
      http.addHeader("X-Device-Secret", deviceSecret);

      String localIp = WiFi.localIP().toString();
      long rssi = WiFi.RSSI();

      String json = "{";
      json += "\"firmware_version\":\"" + String(firmwareVersion) + "\",";
      json += "\"ip\":\"" + localIp + "\",";
      json += "\"rssi\":" + String(rssi);
      json += "}";

      int httpResponseCode = http.POST(json);

      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);
      Serial.print("Request body: ");
      Serial.println(json);

      if (httpResponseCode > 0) {
        String response = http.getString();
        Serial.print("Response: ");
        Serial.println(response);
      } else {
        Serial.print("POST failed, error: ");
        Serial.println(http.errorToString(httpResponseCode));
      }

      http.end();
    } else {
      Serial.println("WiFi Disconnected");
    }

    lastTime = millis();
  }
}
