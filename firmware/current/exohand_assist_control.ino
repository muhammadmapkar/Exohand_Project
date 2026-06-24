#include <Arduino.h>
#include <Servo.h>

const int EMG_FLEXOR   = A0;
const int EMG_EXTENSOR = A1;
const int EMG_EXTRA    = A2;

const int SERVO_PIN = 9;

const int RMS_WINDOW = 40;

const float REST_LEVEL = 0.005;
const float MAX_LEVEL  = 0.05;

const int SERVO_CENTER = 90;
const int SERVO_MIN    = 60;
const int SERVO_MAX    = 120;

Servo servo;

float bufFlex[RMS_WINDOW];
float bufExt[RMS_WINDOW];
float bufExtra[RMS_WINDOW];
int idx = 0;

float computeRMS(float *buf) {
  float sum = 0;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sum += buf[i] * buf[i];
  }
  return sqrt(sum / RMS_WINDOW);
}

void setup() {
  Serial.begin(115200);
  servo.attach(SERVO_PIN);
  servo.write(SERVO_CENTER);
}

void loop() {
  float f = analogRead(EMG_FLEXOR)   / 1023.0;
  float e = analogRead(EMG_EXTENSOR) / 1023.0;
  float x = analogRead(EMG_EXTRA)    / 1023.0;

  bufFlex[idx]  = f;
  bufExt[idx]   = e;
  bufExtra[idx] = x;
  idx = (idx + 1) % RMS_WINDOW;

  float rmsFlex  = computeRMS(bufFlex);
  float rmsExt   = computeRMS(bufExt);
  float rmsExtra = computeRMS(bufExtra);

  float effort = (rmsFlex + rmsExt + rmsExtra) / 3.0;

  Serial.print(rmsFlex); Serial.print(",");
  Serial.print(rmsExt);  Serial.print(",");
  Serial.println(effort);

  int target = SERVO_CENTER;

  if (effort > REST_LEVEL) {

    float assist = constrain(
      (effort - REST_LEVEL) / (MAX_LEVEL - REST_LEVEL),
      0.0,
      1.0
    );

    if (rmsFlex > rmsExt) {
      target = SERVO_CENTER + assist * (SERVO_MAX - SERVO_CENTER);
    }
    else if (rmsExt > rmsFlex) {
      target = SERVO_CENTER - assist * (SERVO_CENTER - SERVO_MIN);
    }
  }

  servo.write(target);
  delay(5);
}
