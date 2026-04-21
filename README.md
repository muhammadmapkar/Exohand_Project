# ExoHand – EMG-Based Assistive Robotic Hand

## Overview

ExoHand is a wearable robotic hand system that uses surface EMG (sEMG) signals from the forearm to control individual finger movements.
The goal is simple: detect muscle activity → process signal → move fingers via servo motors.

This project focuses on assistive augmentation, where user intent is amplified using motors.

---

## Key Features

* Real-time EMG signal acquisition
* Signal filtering (20–450 Hz bandpass + 50 Hz notch)
* RMS-based muscle activation detection
* Multi-finger control (up to 5 servos)
* PWM control using PCA9685
* Wireless telemetry via ESP32-C3 Mini (optional)
* Modular PCB design (Logic + Power separation)

---

## System Architecture

EMG Sensors → Analog Front-End → Teensy 4.0 → PCA9685 → Servo Motors
↓
ESP32-C3 (WiFi Telemetry)

---

## Hardware Components

* Microcontroller: Teensy 4.0
* Servo Driver: PCA9685 (I2C)
* Servos: MG996R (or equivalent)
* EMG Sensors: 3-channel (expandable)
* WiFi Module: ESP32-C3-MINI
* Power Supply: 2S LiPo (7.4V)
* Buck Converter: XL4015 / MP1584
* Connectors: JST (battery), pin headers (I2C, servos)

---

## Signal Processing Pipeline

1. Sample EMG at 1000 Hz
2. Apply Bandpass Filter (20–450 Hz)
3. Apply Notch Filter (50 Hz)
4. Compute RMS (window ~50 ms)
5. Threshold detection
6. Map activation → servo angle

---

## Software Stack

* Arduino IDE + Teensyduino
* Libraries:

  * Wire.h
  * Adafruit_PWMServoDriver.h
  * Servo.h

---

## Example Control Logic

* Read EMG input
* Compute RMS
* If RMS > threshold → move servo
* Else → relax servo

---

## Pin Mapping (Core)

| Component   | From Pin    | To Pin       | Notes        |
| ----------- | ----------- | ------------ | ------------ |
| PCA9685 SDA | Teensy SDA  | I2C Data     | Shared bus   |
| PCA9685 SCL | Teensy SCL  | I2C Clock    | Shared bus   |
| Servos      | PCA9685 PWM | Servo Signal | 5 channels   |
| EMG Out     | Sensor      | Teensy ADC   | Analog input |

---

## PCB Design Notes

* Separate analog and digital ground planes
* Keep EMG traces short and isolated
* Place decoupling capacitors near ICs
* Keep power section away from signal section
* Use wide traces for servo power lines

---

## Power Design

* Battery: 7.4V LiPo
* Step-down to:

  * 6V for servos
  * 5V/3.3V for logic
* Avoid powering servos directly from MCU

---

## Future Improvements

* AI-based gesture classification
* Individual finger isolation using ML
* Dry electrode system
* Compact custom PCB (no modules)
* Mobile/web dashboard for telemetry

---

## Known Challenges

* Noise in EMG signals
* Difficulty isolating finger signals
* Servo current spikes causing voltage drops
* Mechanical alignment of exoskeleton

---

## How to Run

1. Upload firmware to Teensy
2. Connect EMG sensors
3. Power system
4. Open Serial Monitor
5. Adjust threshold values
6. Test finger movement

---

## Repository Structure

```
/hardware
  /pcb
  /schematics

/software
  /firmware
  /signal_processing

/docs
  images
  diagrams
```

---

## Contribution

Open to improvements in:

* Signal processing
* Hardware optimization
* ML integration
* Mechanical design

---

## Author

ExoHand Project – Assistive Robotics System
