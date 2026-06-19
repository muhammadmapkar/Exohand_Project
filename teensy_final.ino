// ExoHand_Teensy.ino
  // Teensy 4.0 — EMG capture, feature extraction, embedded RF classifier,
  // servo drive via PCA9685, UART bridge to ESP32, safety + diagnostics.
  //
  // Libraries needed (Library Manager):
  //   Adafruit PWM Servo Driver Library
  //   Watchdog_t4 (bundled with Teensyduino — no install needed)
  //   EEPROM (built-in)
  //
  // EMG sensor (SEN0240) -> A0
  // I2C: SDA=18, SCL=19  (PCA9685 @0x40)
  // UART1 to WEMOS C3: TX1(pin1)->ESP RX, RX1(pin0)->ESP TX
  
  #include <Wire.h>
  #include <Adafruit_PWMServoDriver.h>
  #include <EEPROM.h>
  #include <Watchdog_t4.h>
  #include "ai_classifier_model.h"
  
  // ---------------- CONFIG ----------------
  #define EMG_PIN A0
  #define SAMPLE_RATE_HZ   1000
  #define WINDOW_SIZE      30
  #define STEP_SIZE        5
  
  #define SCALER_MEAN      463.59002976f
  #define SCALER_SCALE     15.98672036f
  
  Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);
  #define PCA_OSC_FREQ     27000000
  #define SERVO_FREQ_HZ    50
  
  #define CH_PINKY_RING    0
  #define CH_MIDDLE        1
  #define CH_INDEX         2
  #define CH_THUMB         3
  
  #define SERVO_PULSE_MIN  102
  #define SERVO_PULSE_MAX  512
  
  float SERVO_OPEN_ANGLE[4]   = {0, 0, 0, 0};
  float SERVO_CLOSED_ANGLE[4] = {180, 180, 180, 180};
  
  #define SERVO_STEP_DEG     3.0f
  #define SERVO_UPDATE_MS    15
  
  #define CONFIRM_COUNT      4
  #define MIN_HOLD_MS        150
  #define CONFIDENCE_THRESHOLD 0.40f   // below this, treat as "no change"
  
  #define EMG_SEND_INTERVAL_MS  20
  #define HEARTBEAT_INTERVAL_MS 500
  #define CONFIDENCE_SEND_MS    200
  
  // Baseline calibration
  #define BASELINE_CAPTURE_MS 1000
  
  // EEPROM
  #define EEPROM_MAGIC 0xA5
  
  // Watchdog
  WDT_T4<WDT1> wdt;
  #define WDT_TIMEOUT_S 2
  
  // ---------------- STATE ----------------
  volatile int sampleBuf[WINDOW_SIZE];
  volatile int bufHead = 0;
  volatile int samplesSinceClassify = 0;
  volatile bool bufFull = false;
  volatile int lastRawSample = 0;
  
  IntervalTimer sampleTimer;
  
  float currentAngle[4];
  float targetAngle[4];
  unsigned long lastServoUpdate = 0;
  
  char confirmedGesture[16] = "rest";
  char history[CONFIRM_COUNT][16];
  int historyIdx = 0;
  unsigned long lastGestureChange = 0;
  
  unsigned long lastEmgSend = 0;
  unsigned long lastHeartbeat = 0;
  unsigned long lastConfidenceSend = 0;
  
  float restBaselineMAV = 0;
  float lastConfidence = 0;
  
  struct CalibData {
    uint8_t magic;
    float openAngle[4];
    float closedAngle[4];
  };
  
  // ---------------- ISR: 1kHz sampling ----------------
  void sampleISR() {
    int v = analogRead(EMG_PIN);
    lastRawSample = v;
    sampleBuf[bufHead] = v;
    bufHead = (bufHead + 1) % WINDOW_SIZE;
    samplesSinceClassify++;
    if (bufHead == 0) bufFull = true;
  }
  
  // ---------------- Feature extraction ----------------
  void getOrderedWindow(int out[WINDOW_SIZE]) {
    noInterrupts();
    int head = bufHead;
    for (int i = 0; i < WINDOW_SIZE; i++) {
      out[i] = sampleBuf[(head + i) % WINDOW_SIZE];
    }
    interrupts();
  }
  
  void extractFeatures(int w[WINDOW_SIZE], float feat[RF_NUM_FEATURES]) {
    float mean = 0;
    for (int i = 0; i < WINDOW_SIZE; i++) mean += w[i];
    mean /= WINDOW_SIZE;
  
    float mav = 0, sumSq = 0, wl = 0;
    for (int i = 0; i < WINDOW_SIZE; i++) {
      mav += fabsf(w[i]);
      sumSq += (float)w[i] * w[i];
    }
    mav /= WINDOW_SIZE;
    float rms = sqrtf(sumSq / WINDOW_SIZE);
  
    for (int i = 0; i < WINDOW_SIZE - 1; i++) wl += fabsf(w[i + 1] - w[i]);
  
    float variance = 0;
    for (int i = 0; i < WINDOW_SIZE; i++) {
      float d = w[i] - mean;
      variance += d * d;
    }
    variance /= WINDOW_SIZE;
    float stddev = sqrtf(variance);
  
    int zcr = 0;
    for (int i = 0; i < WINDOW_SIZE - 1; i++) {
      float a = w[i] - mean, b = w[i + 1] - mean;
      if (a * b < 0) zcr++;
    }
  
    int ssc = 0;
    for (int i = 1; i < WINDOW_SIZE - 1; i++) {
      float d1 = (float)w[i] - w[i - 1];
      float d2 = (float)w[i + 1] - w[i];
      if (d1 * d2 < 0) ssc++;
    }
  
    float skew = 0, kurt = 0;
    if (stddev > 0.0001f) {
      for (int i = 0; i < WINDOW_SIZE; i++) {
        float z = (w[i] - mean) / stddev;
        skew += z * z * z;
        kurt += z * z * z * z;
      }
      skew /= WINDOW_SIZE;
      kurt = (kurt / WINDOW_SIZE) - 3.0f;
    }
  
    int sorted[WINDOW_SIZE];
    for (int i = 0; i < WINDOW_SIZE; i++) sorted[i] = w[i];
    for (int i = 1; i < WINDOW_SIZE; i++) {
      int key = sorted[i], j = i - 1;
      while (j >= 0 && sorted[j] > key) {
        sorted[j + 1] = sorted[j];
        j--;
      }
      sorted[j + 1] = key;
    }
    auto percentile = [&](float p) -> float {
      float idx = p * (WINDOW_SIZE - 1);
      int lo = (int)idx;
      int hi = lo + 1 < WINDOW_SIZE ? lo + 1 : lo;
      float frac = idx - lo;
      return sorted[lo] + frac * (sorted[hi] - sorted[lo]);
    };
    float iqr = percentile(0.75f) - percentile(0.25f);
  
    feat[0] = (mav - SCALER_MEAN) / SCALER_SCALE;
    feat[1] = rms;
    feat[2] = variance;
    feat[3] = stddev;
    feat[4] = wl;
    feat[5] = (float)zcr;
    feat[6] = (float)ssc;
    feat[7] = skew;
    feat[8] = kurt;
    feat[9] = iqr;
  }
  
  // ---------------- RF inference (hard majority vote + confidence) ----------------
  int predictTree(int treeIdx, float feat[RF_NUM_FEATURES]) {
    int16_t idx = RF_TREE_ROOTS[treeIdx];
    while (RF_NODES[idx].feature != -1) {
      if (feat[RF_NODES[idx].feature] <= RF_NODES[idx].threshold)
        idx = RF_NODES[idx].left;
      else
        idx = RF_NODES[idx].right;
    }
    return RF_NODES[idx].leaf_class;
  }
  
  int classify(float feat[RF_NUM_FEATURES], float* confidenceOut) {
    int votes[RF_NUM_CLASSES] = {0};
    for (int t = 0; t < RF_NUM_TREES; t++) votes[predictTree(t, feat)]++;
    int best = 0;
    for (int c = 1; c < RF_NUM_CLASSES; c++) if (votes[c] > votes[best]) best = c;
    if (confidenceOut) *confidenceOut = (float)votes[best] / RF_NUM_TREES;
    return best;
  }
  
  // ---------------- Debounce ----------------
  void pushHistory(const char* label) {
    strncpy(history[historyIdx], label, 15);
    historyIdx = (historyIdx + 1) % CONFIRM_COUNT;
  }
  
  bool historyAllAgree(const char* label) {
    for (int i = 0; i < CONFIRM_COUNT; i++) {
      if (strcmp(history[i], label) != 0) return false;
    }
    return true;
  }
  
  // ---------------- Gesture -> servo targets ----------------
  void applyGestureTargets(const char* g) {
    for (int i = 0; i < 4; i++) targetAngle[i] = SERVO_OPEN_ANGLE[i];
  
    if (strcmp(g, "fist") == 0) {
      for (int i = 0; i < 4; i++) targetAngle[i] = SERVO_CLOSED_ANGLE[i];
    } else if (strcmp(g, "pinky&ring") == 0) {
      targetAngle[CH_PINKY_RING] = SERVO_CLOSED_ANGLE[CH_PINKY_RING];
    } else if (strcmp(g, "middle") == 0) {
      targetAngle[CH_MIDDLE] = SERVO_CLOSED_ANGLE[CH_MIDDLE];
    } else if (strcmp(g, "index") == 0) {
      targetAngle[CH_INDEX] = SERVO_CLOSED_ANGLE[CH_INDEX];
    } else if (strcmp(g, "thumb") == 0) {
      targetAngle[CH_THUMB] = SERVO_CLOSED_ANGLE[CH_THUMB];
    }
  }
  
  void writeServoAngle(int ch, float angle) {
    int pulse = (int)(SERVO_PULSE_MIN + (angle / 180.0f) * (SERVO_PULSE_MAX - SERVO_PULSE_MIN));
    pwm.setPWM(ch, 0, pulse);
  }
  
  void updateServosSmooth() {
    if (millis() - lastServoUpdate < SERVO_UPDATE_MS) return;
    lastServoUpdate = millis();
    for (int i = 0; i < 4; i++) {
      float diff = targetAngle[i] - currentAngle[i];
      if (fabsf(diff) <= SERVO_STEP_DEG) {
        currentAngle[i] = targetAngle[i];
      } else {
        currentAngle[i] += (diff > 0 ? SERVO_STEP_DEG : -SERVO_STEP_DEG);
      }
      writeServoAngle(i, currentAngle[i]);
    }
  }
  
  // ---------------- EEPROM calibration ----------------
  void saveCalibration() {
    CalibData c;
    c.magic = EEPROM_MAGIC;
    for (int i = 0; i < 4; i++) {
      c.openAngle[i] = SERVO_OPEN_ANGLE[i];
      c.closedAngle[i] = SERVO_CLOSED_ANGLE[i];
    }
    EEPROM.put(0, c);
    Serial.println("Calibration saved");
  }
  
  void loadCalibration() {
    CalibData c;
    EEPROM.get(0, c);
    if (c.magic == EEPROM_MAGIC) {
      for (int i = 0; i < 4; i++) {
        SERVO_OPEN_ANGLE[i] = c.openAngle[i];
        SERVO_CLOSED_ANGLE[i] = c.closedAngle[i];
      }
      Serial.println("Calibration loaded from EEPROM");
    } else {
      saveCalibration();
      Serial.println("No calibration found, defaults saved");
    }
  }
  
  // Serial commands: "O0 15" open ch0=15 | "C3 170" closed ch3=170 | "SAVE" | "PRINT"
  void handleSerialCommands() {
    if (!Serial.available()) return;
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() < 2) return;
  
    if (cmd == "SAVE") {
      saveCalibration();
      return;
    }
    if (cmd == "PRINT") {
      for (int i = 0; i < 4; i++) {
        Serial.print("CH"); Serial.print(i);
        Serial.print(" open="); Serial.print(SERVO_OPEN_ANGLE[i]);
        Serial.print(" closed="); Serial.println(SERVO_CLOSED_ANGLE[i]);
      }
      return;
    }
  
    char type = cmd.charAt(0);
    int ch = cmd.charAt(1) - '0';
    int spaceIdx = cmd.indexOf(' ');
    if ((type == 'O' || type == 'C') && ch >= 0 && ch < 4 && spaceIdx > 0) {
      float angle = cmd.substring(spaceIdx + 1).toFloat();
      if (type == 'O') SERVO_OPEN_ANGLE[ch] = angle;
      else SERVO_CLOSED_ANGLE[ch] = angle;
      Serial.print("Set "); Serial.print(type); Serial.print(ch);
      Serial.print(" = "); Serial.println(angle);
    }
  }
  
  // ---------------- Baseline auto-calibration ----------------
  void captureBaseline() {
    Serial.println("Capturing rest baseline, keep hand relaxed...");
    unsigned long start = millis();
    long sum = 0;
    int count = 0;
    while (millis() - start < BASELINE_CAPTURE_MS) {
      sum += analogRead(EMG_PIN);
      count++;
      delay(1);
    }
    restBaselineMAV = (float)sum / count;
    Serial.print("Baseline MAV: "); Serial.println(restBaselineMAV);
  }
  
  // ---------------- Startup sweep test ----------------
  void sweepTest() {
    Serial.println("Servo sweep test...");
    for (int i = 0; i < 4; i++) {
      writeServoAngle(i, SERVO_CLOSED_ANGLE[i]);
      delay(300);
      writeServoAngle(i, SERVO_OPEN_ANGLE[i]);
      delay(300);
    }
    Serial.println("Sweep test done");
  }
  
  // ---------------- Setup ----------------
  void setup() {
    Serial.begin(115200);
    Serial1.begin(115200);
  
    analogReadResolution(10);
  
    Wire.begin();
    pwm.begin();
    pwm.setOscillatorFrequency(PCA_OSC_FREQ);
    pwm.setPWMFreq(SERVO_FREQ_HZ);
  
    loadCalibration();
  
    for (int i = 0; i < 4; i++) {
      currentAngle[i] = SERVO_OPEN_ANGLE[i];
      targetAngle[i] = SERVO_OPEN_ANGLE[i];
    }
    delay(200);
    for (int i = 0; i < 4; i++) writeServoAngle(i, currentAngle[i]);
  
    sweepTest();
    captureBaseline();
  
    for (int i = 0; i < CONFIRM_COUNT; i++) strncpy(history[i], "rest", 15);
  
    WDT_timings_t config;
    config.trigger = 1;
    config.timeout = WDT_TIMEOUT_S;
    wdt.begin(config);
  
    sampleTimer.begin(sampleISR, 1000000 / SAMPLE_RATE_HZ);
  }
  
  // ---------------- Loop ----------------
  void loop() {
    wdt.feed();
    handleSerialCommands();
  
    if (bufFull && samplesSinceClassify >= STEP_SIZE) {
      noInterrupts();
      samplesSinceClassify = 0;
      interrupts();
  
      int window[WINDOW_SIZE];
      getOrderedWindow(window);
  
      float feat[RF_NUM_FEATURES];
      extractFeatures(window, feat);
  
      float confidence;
      int classIdx = classify(feat, &confidence);
      lastConfidence = confidence;
  
      const char* label = RF_CLASS_NAMES[classIdx];
      if (confidence < CONFIDENCE_THRESHOLD) label = confirmedGesture;
  
      pushHistory(label);
      if (historyAllAgree(label) &&
          strcmp(label, confirmedGesture) != 0 &&
          millis() - lastGestureChange > MIN_HOLD_MS) {
        strncpy(confirmedGesture, label, 15);
        lastGestureChange = millis();
        applyGestureTargets(confirmedGesture);
  
        Serial1.print("G,");
        Serial1.println(confirmedGesture);
      }
    }
    updateServosSmooth();
  
    if (millis() - lastEmgSend >= EMG_SEND_INTERVAL_MS) {
      lastEmgSend = millis();
      // Legacy UART bridge to the ESP32 (harmless if the ESP32 is absent/fried).
      Serial1.print("E,");
      Serial1.println(lastRawSample);
      // USB Serial: emit the raw EMG sample as a plain number, one per line.
      // This drives BOTH the Teensyduino Serial Plotter graph AND the website's
      // Web Serial reader (parsePlotterLine -> feedPlotter mirrors this exact
      // waveform on the live chart). Keep this line numbers-only so the Serial
      // Plotter trace stays clean.
      Serial.println(lastRawSample);
    }
  
    if (millis() - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeat = millis();
      Serial1.print("H,");
      Serial1.println(millis());
    }
  
    if (millis() - lastConfidenceSend >= CONFIDENCE_SEND_MS) {
      lastConfidenceSend = millis();
      Serial1.print("C,");
      Serial1.println((int)(lastConfidence * 100));
    }
  }