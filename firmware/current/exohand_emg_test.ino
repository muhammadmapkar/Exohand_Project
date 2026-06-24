#include <Arduino.h>  
#include <Servo.h>

const int EMG_PIN = A0;
const int SERVO_PIN = 9;

const int RMS_WINDOW = 50;
const float THRESHOLD = 0.02;

Servo servo;

float emgBuffer[RMS_WINDOW];
int bufferIndex = 0;

float computeRMS() {
  float sum = 0;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sum += emgBuffer[i] * emgBuffer[i];
  }
  return sqrt(sum / RMS_WINDOW);
}

void setup() {
  Serial.begin(115200);
  servo.attach(SERVO_PIN);
  servo.write(90);
}

void loop() {
  int raw = analogRead(EMG_PIN);
  float emg = raw / 1023.0;

  emgBuffer[bufferIndex++] = emg;
  if (bufferIndex >= RMS_WINDOW) bufferIndex = 0;

  float rms = computeRMS();

  Serial.println(rms);

  if (rms > THRESHOLD) {
    servo.write(120);
  } else {
    servo.write(90);
  }

  delay(5);
}
