#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

#define EMG_PIN A0
#define SERVO_CHANNEL 0

// MG996R safe angle limits
#define SERVO_MIN_ANGLE 20
#define SERVO_MAX_ANGLE 160

// Pulse range for PCA9685
#define SERVO_MIN 120
#define SERVO_MAX 620

#define RMS_WINDOW 50
#define THRESHOLD 0.05

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

float emgBuffer[RMS_WINDOW];
int bufferIndex = 0;

float computeRMS() {
  float sum = 0;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sum += emgBuffer[i] * emgBuffer[i];
  }
  return sqrt(sum / RMS_WINDOW);
}

uint16_t angleToPulse(int angle) {
  return map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
}

void setup() {
  Serial.begin(115200);

  pwm.begin();
  pwm.setPWMFreq(50);

  delay(10);
}

void loop() {

  int raw = analogRead(EMG_PIN);
  float emg = raw / 1023.0;

  emgBuffer[bufferIndex++] = emg;
  if (bufferIndex >= RMS_WINDOW) bufferIndex = 0;

  float rms = computeRMS();
  Serial.println(rms);

  int angle;

  if (rms > THRESHOLD) {
    angle = SERVO_MAX_ANGLE;   // Close
  } else {
    angle = SERVO_MIN_ANGLE;   // Open
  }

  pwm.setPWM(SERVO_CHANNEL, 0, angleToPulse(angle));

  delay(1);
}
