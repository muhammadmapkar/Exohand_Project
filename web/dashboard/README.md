# ExoHand Live EMG Gesture Dashboard

Real-time browser-based dashboard that reads EMG signals from a **Teensy 4.1** via serial, classifies hand gestures using a pre-trained **Random Forest** model, and displays predictions live — no terminal interaction required.

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 📁 File Structure

```
ExoHand_Live_Dashboard/
├── app.py                        ← FastAPI backend (serial + model + WebSocket)
├── requirements.txt              ← Python dependencies
├── templates/
│   └── index.html                ← Dashboard HTML
├── static/
│   ├── style.css                 ← Dark theme CSS
│   └── app.js                    ← Frontend logic + Chart.js
├── README.md                     ← This file
│
│  (Place these model files here or in the parent directory)
├── ExoHand_RF_Model.joblib       ← Trained Random Forest model
└── ExoHand_Scaler.joblib         ← EMG Input Scaler
```

---

## 1. Place the Model Files

Copy these three `.pkl` files (exported from Google Colab) into **this folder** or its **parent folder**:

| File | Purpose |
|---|---|
| `ExoHand_RF_Model.joblib` | Trained Random Forest classifier |
| `ExoHand_Scaler.joblib` | EMG Input Scaler |

---

## 2. Install Requirements

Open a terminal in this directory and run:

```bash
pip install -r requirements.txt
```

This installs: `fastapi`, `uvicorn`, `websockets`, `pyserial`, `numpy`, `pandas`, `scikit-learn`, `joblib`, `jinja2`.

---

## 3. Upload Teensy Arduino Code

Flash the following code to your **Teensy 4.1** using the Arduino IDE:

```cpp
const int EMG_PIN = A0;

int baseline = 0;

void setup() {
  Serial.begin(115200);

  long total = 0;

  for (int i = 0; i < 500; i++) {
    total += analogRead(EMG_PIN);
    delay(1);
  }

  baseline = total / 500;
}

void loop() {
  int raw = analogRead(EMG_PIN);
  int signal = abs(raw - baseline);

  Serial.println(signal);

  delay(20);
}
```

### What this does:
- Reads the EMG sensor on analog pin **A0**
- Calibrates a baseline from the first 500 samples
- Sends `abs(raw - baseline)` over serial at **115200 baud**
- One numeric value per line, ~50 samples/second (20 ms delay)

---

## 4. Close the Arduino Serial Monitor

> ⚠ **Only one application can access a serial port at a time.**

Before running the dashboard, **close the Arduino Serial Monitor** (or any other program using the serial port). Otherwise the dashboard will fail to connect.

---

## 5. Run the Dashboard

```bash
python app.py
```

Then open your browser at:

```
http://127.0.0.1:8000
```

You should see the ExoHand Live EMG Gesture Dashboard.

---

## 6. Using the Dashboard

1. **Refresh Ports** — Click 🔄 Refresh to detect available serial ports.
2. **Select Port** — Choose the Teensy serial port from the dropdown (e.g. `/dev/cu.usbmodem14101` on macOS).
3. **Connect** — Click ▶ Connect. The dashboard starts reading live EMG data.
4. **Watch Predictions** — The prediction card updates in real time with the classified gesture, confidence percentage, and a colour-coded display.
5. **Live Graph** — The EMG signal chart shows the last 200 samples continuously.
6. **Gesture History** — The last 10 gesture changes are shown with timestamps and confidence.
7. **Disconnect** — Click ■ Disconnect when done.

---

## Demo Mode (No Hardware Required)

If you don't have the Teensy connected, click the **🎮 Demo Mode** button in the connection panel. This generates fake EMG data at ~50 Hz and runs it through the real Random Forest model, so you can verify that the graph, prediction card, gesture history, and all UI elements work correctly.

---

## 7. Troubleshooting

| Problem | Solution |
|---|---|
| **"Could not open port"** | Close the Arduino Serial Monitor. Only one app can use a serial port. |
| **No ports listed** | Check that the Teensy is plugged in via USB. Click 🔄 Refresh. |
| **"Model not found"** | Make sure the `.pkl` files are in this folder or its parent folder. |
| **Graph shows no data** | Ensure the Teensy code is uploaded and printing values. Check baud rate (115200). |
| **Predictions say "Calibrating"** | Wait for 25 samples to fill the sliding window (~0.5 seconds). |
| **Predictions seem wrong** | The model was trained on specific gestures. Ensure your EMG sensor placement matches training conditions. |
| **WebSocket disconnects** | The dashboard auto-reconnects. If persistent, restart `app.py`. |
| **Import errors** | Run `pip install -r requirements.txt` again. |
| **Port permission denied (Linux)** | Run `sudo chmod 666 /dev/ttyACM0` or add your user to the `dialout` group. |
| **Port busy error** | The Arduino Serial Monitor is still open. Close it and try again. |

---

## Diagnostic Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/ports` | GET | List available serial ports |
| `/api/connect` | POST | Connect to a serial port (`{"port": "...", "baud": 115200}`) |
| `/api/disconnect` | POST | Disconnect from the serial port |
| `/api/demo` | POST | Start demo mode (fake EMG data) |
| `/api/test-serial` | GET | Read 10 raw serial values and return them as JSON (for debugging) |
| `/ws/live` | WebSocket | Live EMG + prediction data stream |

---

## Technical Details
 
 - **Sliding window**: 30 samples (~0.6 s at 50 Hz)
 - **Prediction trigger**: Every 5 new samples
 - **Smoothing**: Majority vote over the last 5 predictions
 - **Features extracted**: `MAV`, `RMS`, `Variance`, `Std`, `WL`, `ZCR`, `SSC`, `Skew`, `Kurtosis`, `IQR`
 - **Gestures**: `fist`, `index`, `middle`, `pinky&ring`, `rest`, `thumb`
 - **Backend → Frontend**: WebSocket at `/ws/live` streaming JSON at ~50 Hz
