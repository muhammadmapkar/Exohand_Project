/*
  ExoHand ESP32 Bridge Firmware
  
  This code runs on the ESP32. It acts as a bridge between the Teensy 4.0 (connected via UART)
  and the website dashboard (hosted on Vercel or run locally) using a WebSocket server.
  
  Connections:
    Teensy TX (Pin 1) -> ESP32 RX (e.g. GPIO 16 / RX2 or GPIO 3 / RX0 depending on setup)
    Teensy RX (Pin 0) -> ESP32 TX (e.g. GPIO 17 / TX2 or GPIO 1 / TX0 depending on setup)
    GND -> GND (Common Ground is CRITICAL!)
    
  Libraries required:
    - WebSockets by Markus Sattler (Install via Library Manager)
*/

#include <WiFi.h>
#include <WebSocketsServer.h>

// --- WiFi Configurations ---
const char* ssid = "ExoHand_Live";
const char* password = "exohandpass"; // Must be at least 8 characters

// --- WebSocket Port (Default is 81 on the website dashboard) ---
const int webSocketPort = 81;

WebSocketsServer webSocket = WebSocketsServer(webSocketPort);

// --- Serial Connection to Teensy ---
// On ESP32, we prefer to use Serial2 for communication with external devices 
// to keep Serial (USB) free for debugging.
#define RXD2 16
#define TXD2 17

void webSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.printf("[%u] Disconnected!\n", num);
      break;
    case WStype_CONNECTED: {
      IPAddress ip = webSocket.remoteIP(num);
      Serial.printf("[%u] Connected from %d.%d.%d.%d url: %s\n", num, ip[0], ip[1], ip[2], ip[3], payload);
      webSocket.sendTXT(num, "Connected to ExoHand ESP32 Bridge");
      break;
    }
    case WStype_TEXT:
      // Forward commands from website (WebSocket) to Teensy (Serial2)
      Serial.printf("[%u] Received command: %s\n", num, payload);
      Serial2.println((char*)payload);
      break;
    case WStype_BIN:
      break;
    default:
      break;
  }
}

void setup() {
  // Start debug USB Serial
  Serial.begin(115200);
  delay(1000);
  
  // Start Serial2 to Teensy 4.0 (Baud rate must match Teensy: 115200)
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2);
  
  Serial.println("\nExoHand ESP32 Bridge Starting...");

  // Configure ESP32 as an Access Point
  WiFi.softAP(ssid, password);
  IPAddress IP = WiFi.softAPIP();
  
  Serial.print("WiFi AP Created. SSID: ");
  Serial.println(ssid);
  Serial.print("ESP32 IP Address: ");
  Serial.println(IP); // By default, this is usually 192.168.4.1

  // Start WebSocket Server
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
  
  Serial.printf("WebSocket Server started on port %d\n", webSocketPort);
}

void loop() {
  webSocket.loop();
  
  // 1. Read incoming data from Teensy (Serial2) and broadcast to WebSocket client
  static String inputBuffer = "";
  while (Serial2.available() > 0) {
    char c = Serial2.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        // Broadcast the line (EMG data / labels) directly to the web dashboard
        webSocket.broadcastTXT(inputBuffer);
        
        // Debug output to Serial Monitor
        Serial.print("Bridge -> Browser: ");
        Serial.println(inputBuffer);
      }
      inputBuffer = "";
    } else if (c != '\r') {
      inputBuffer += c;
    }
  }

  // 2. Mirror debug messages from USB Serial to Teensy (for manual testing)
  while (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    Serial2.println(cmd);
  }
}
