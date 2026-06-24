// ExoHand - Servo Test Only
// Cycles each channel, then all together

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

#define SERVO_FREQ 50
#define SERVOMIN 150
#define SERVOMAX 600

#define CH_PINKY_RING 0
#define CH_MIDDLE 1
#define CH_INDEX 2
#define CH_THUMB 3

void setup() {
  Serial.begin(115200);
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(SERVO_FREQ);
  delay(500);
}

void loop() {
  testChannel(CH_PINKY_RING, "Pinky/Ring");
  testChannel(CH_MIDDLE, "Middle");
  testChannel(CH_INDEX, "Index");
  testChannel(CH_THUMB, "Thumb");

  Serial.println("All together");
  allTo(SERVOMAX);
  delay(800);
  allTo(SERVOMIN);
  delay(800);
}

void testChannel(uint8_t ch, const char* name) {
  Serial.print("Testing: ");
  Serial.println(name);
  pwm.setPWM(ch, 0, SERVOMAX);
  delay(600);
  pwm.setPWM(ch, 0, SERVOMIN);
  delay(600);
}

void allTo(int pos) {
  pwm.setPWM(CH_PINKY_RING, 0, pos);
  pwm.setPWM(CH_MIDDLE, 0, pos);
  pwm.setPWM(CH_INDEX, 0, pos);
  pwm.setPWM(CH_THUMB, 0, pos);
}
