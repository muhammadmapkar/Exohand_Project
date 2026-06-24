# ExoHand

EMG-controlled assistive robotic hand. Built for ECTE351 by Team Orvyn (Group 19).

## Overview

ExoHand reads surface EMG (sEMG) from the forearm, classifies the muscle activity into a hand gesture, and drives four servo-actuated fingers to match. The current system recognizes `rest`, `fist`, and individual-finger gestures (`pinky&ring`, `middle`, `index`, `thumb`), running the trained classifier directly on the microcontroller. VR integration is planned; not yet in this codebase. — see `docs/architecture.md`. Runs the trained classifier on-device (no PC needed for inference).

## EMG-control concept

1. Sample raw EMG at 1 kHz from a single sensor channel.
2. Extract statistical features (MAV, RMS, variance, std dev, waveform length, zero-crossing rate, slope sign changes, skewness, kurtosis, IQR) over a rolling 30-sample window.
3. Classify the window with a Random Forest trained on EMG collected by the team (plus validation against the public NinaPro benchmark dataset).
4. Debounce the result (4 agreeing windows + 150ms hold) before committing to a new gesture.
5. Drive 4 servos through a PCA9685 to match the confirmed gesture, moving smoothly rather than snapping.

Full signal-flow diagram: `docs/architecture.md`.

## Hardware stack

- Teensy 4.0 (main firmware). The dashboard backend references 4.1; project standardized on 4.0.
- PCA9685 servo driver (I2C, 4 channels)
- MG996R servos (or equivalent)
- SEN0240 EMG sensor
- ESP32-C3, for live telemetry/graph relay (`firmware/current/esp32_bridge.ino` — self-hosted WiFi AP + WebSocket server)

## Repo layout

```
exohand/
├── firmware/        Teensy/ESP32 .ino code — current/ is what's in active use, archive/ is superseded versions
├── web/             static site + the FastAPI live dashboard
├── hardware/        KiCad schematics/PCB, BOM, perfboard build docs
├── signal-processing/  EMG filtering, feature extraction, trained model, datasets
├── docs/            build-log, architecture, decisions, posters
└── media/           screenshots, recordings, concept art
```

Nothing failed or superseded was deleted — old firmware versions, every dated PCB backup, duplicate dataset exports, and earlier notebook runs are all kept under the relevant `archive/` folders. See `docs/build-log.md` for the full story of what was tried and what changed.

## How to build / run

**Firmware:** open `firmware/current/ExoHand_Teensy.ino` in Arduino IDE with Teensyduino, plus the Adafruit PWM Servo Driver library. Note: this sketch includes `ai_classifier_model.h`, which is not present in this repo — it needs to be regenerated from `signal-processing/ExoHand_RF_Model.joblib` (a standard sklearn-Random-Forest-to-C-array conversion) before it will compile. See `docs/build-log.md` for why.

**Signal processing / training:** `pip install -r signal-processing/requirements.txt`, then `signal-processing/ExoHand_EMG_Classifier_RF_V2.ipynb` to retrain, or `signal-processing/live_predict.py` to run live PC-side inference over serial.

**Live dashboard:** `web/dashboard/app.py` (FastAPI). Install `web/dashboard/requirements.txt`, run with `uvicorn app:app`, open the browser page it serves. Includes a `/api/demo` mode that fakes EMG data if no hardware is connected.

**Website:** `web/website.html` is the current main site (Live Rehab dashboard view, live EMG chart, camera-based sensor-placement assistant). `web/archive/ORVYNUpdated.html` is an earlier, less developed version.

**Hardware:** schematics and PCB in `hardware/schematics/`, BOM in `hardware/bom/`, perfboard wiring/assembly in `hardware/perfboard/`.

## Credit

Team Orvyn (Group 19). My role: led firmware (Teensy), EMG signal processing, hardware build. Data collection was team effort. Benchmark data from NinaPro.
