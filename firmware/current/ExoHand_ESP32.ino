// ExoHand_ServoTest.ino
// Pure servo test - no EMG. Cycles each servo individually, then all
// four together, on a loop. Use this to confirm wiring/channels before
// touching EMG logic at all.

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define I2C_SDA 21
#define I2C_SCL 22

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);
#define PCA_OSC_FREQ 27000000
#define SERVO_FREQ_HZ 50
#define NUM_SERVOS 4
#define SERVO_PULSE_MIN 102
#define SERVO_PULSE_MAX 512
#define OPEN_ANGLE   0
#define CLOSED_ANGLE 180

// channel order: 0=pinky&ring, 1=middle, 2=index, 3=thumb
const char* servoNames[NUM_SERVOS] = {"pinky&ring", "middle", "index", "thumb"};

void writeServoAngle(int ch, float angle) {
  int pulse = (int)(SERVO_PULSE_MIN + (angle / 180.0f) * (SERVO_PULSE_MAX - SERVO_PULSE_MIN));
  pwm.setPWM(ch, 0, pulse);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);
  pwm.begin();
  pwm.setOscillatorFrequency(PCA_OSC_FREQ);
  pwm.setPWMFreq(SERVO_FREQ_HZ);

  for (int i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, OPEN_ANGLE);
  delay(500);
}

void loop() {
  // Test each servo one at a time
  for (int i = 0; i < NUM_SERVOS; i++) {
    Serial.print("Testing channel "); Serial.print(i);
    Serial.print(" ("); Serial.print(servoNames[i]); Serial.println(")");

    writeServoAngle(i, CLOSED_ANGLE);
    delay(600);
    writeServoAngle(i, OPEN_ANGLE);
    delay(600);
  }

  // Then all four together
  Serial.println("Testing all four together");
  for (int i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, CLOSED_ANGLE);
  delay(800);
  for (int i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, OPEN_ANGLE);
  delay(800);

  Serial.println("--- loop complete ---");
  delay(1000);
}