"""
ExoHand Live EMG Gesture Dashboard — FastAPI Backend
=====================================================
Reads EMG data from a Teensy 4.0 via serial, runs real-time gesture
classification with a pre-trained Random Forest model, and streams
predictions to a browser dashboard over WebSocket.

Also includes a /api/demo endpoint to generate fake EMG data for
UI testing without hardware.
"""

import os
import sys
import json
import time
import math
import random
import asyncio
import threading
import collections
import warnings
import logging
from datetime import datetime

# Suppress sklearn version mismatch warnings from unpickling
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import serial
import serial.tools.list_ports
import numpy as np
import pandas as pd
import joblib
from scipy.stats import skew, kurtosis

# ---------------------------------------------------------------------------
# Logging — verbose so every step is visible in the terminal
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("exohand")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(title="ExoHand Live EMG Dashboard")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ---------------------------------------------------------------------------
# Load saved model artefacts (DO NOT retrain)
# ---------------------------------------------------------------------------
MODEL_PATH  = "/Users/muhammadnazirahmedmapkar/Documents/ExoHand_RF_Model.joblib"
SCALER_PATH = "/Users/muhammadnazirahmedmapkar/Documents/ExoHand_Scaler.joblib"


def _load_artefact(path: str, description: str):
    if not os.path.exists(path):
        logger.critical("✗ MISSING %s — expected at: %s", description, path)
        sys.exit(1)
    try:
        data = joblib.load(path)
        logger.info("✓ Loaded %s  ←  %s", description, path)
        return data
    except Exception as exc:
        logger.critical("✗ Failed to load %s from %s: %s", description, path, exc)
        sys.exit(1)


model  = _load_artefact(MODEL_PATH,  "Random Forest model")
scaler = _load_artefact(SCALER_PATH, "EMG Scaler")


class ModelLabelEncoder:
    """Mock LabelEncoder using model.classes_ for seamless backward compatibility."""
    def __init__(self, classes):
        self.classes_ = np.array(classes)
    def inverse_transform(self, indices):
        return [self.classes_[idx] for idx in indices]


label_encoder = ModelLabelEncoder(model.classes_)

# 10 features in exact order as requested
FEATURE_NAMES = ["MAV", "RMS", "Variance", "Std", "WL", "ZCR", "SSC", "Skew", "Kurtosis", "IQR"]
feature_columns = FEATURE_NAMES

logger.info("Gesture classes : %s", list(label_encoder.classes_))
logger.info("Feature columns : %s", feature_columns)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_SIZE   = 30   # sliding window length
PREDICT_EVERY = 5    # predict after this many new samples
VOTE_HISTORY  = 5    # majority-vote depth

# ---------------------------------------------------------------------------
# Shared serial state (single-device model)
# ---------------------------------------------------------------------------

class SerialState:
    """Mutable state shared between the API handlers and the reader thread."""

    def __init__(self):
        self.ser: serial.Serial | None = None
        self.connected: bool = False
        self.port: str | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()

        # Signal processing
        self.window: collections.deque = collections.deque(maxlen=WINDOW_SIZE)
        self.predictions_history: collections.deque = collections.deque(maxlen=VOTE_HISTORY)
        self.new_samples: int = 0
        self.total_samples: int = 0

        # Last known outputs (persist between samples)
        self.last_prediction: str = "waiting"
        self.last_confidence: float = 0.0
        self.latest_raw: float = 0.0

        # Asyncio event loop reference (set on connect)
        self.loop: asyncio.AbstractEventLoop | None = None

        # Demo mode flag
        self.demo_mode: bool = False

    def reset_buffers(self):
        self.window.clear()
        self.predictions_history.clear()
        self.new_samples = 0
        self.total_samples = 0
        self.last_prediction = "waiting"
        self.last_confidence = 0.0
        self.latest_raw = 0.0


state = SerialState()

# Connected WebSocket clients — each gets its own asyncio.Queue
client_queues: list[asyncio.Queue] = []

# ---------------------------------------------------------------------------
# Feature extraction (must match training pipeline)
# ---------------------------------------------------------------------------

def extract_features(window):
    """Compute the 10 time-domain features from a window of EMG samples."""
    arr = np.array(window, dtype=np.float64)
    mav = np.mean(np.abs(arr))
    rms = np.sqrt(np.mean(arr**2))
    var = np.var(arr)
    std = np.std(arr)
    wl = np.sum(np.abs(np.diff(arr)))
    zcr = np.sum(np.diff(np.sign(arr)) != 0)
    ssc = np.sum(np.diff(np.sign(np.diff(arr))) != 0)
    
    sk_val = skew(arr)
    kt_val = kurtosis(arr)
    
    sk = 0.0 if np.isnan(sk_val) else sk_val
    kt = 0.0 if np.isnan(kt_val) else kt_val
    
    iqr = np.percentile(arr, 75) - np.percentile(arr, 25)
    return [mav, rms, var, std, wl, zcr, ssc, sk, kt, iqr]

# ---------------------------------------------------------------------------
# Background serial reader thread
# ---------------------------------------------------------------------------

def _broadcast(data: dict):
    """Enqueue a data dict to every connected WebSocket client."""
    if not state.loop:
        return
    if not client_queues:
        # No WebSocket clients connected yet — this is expected during the
        # brief gap between POST /api/connect returning and the browser
        # opening the WebSocket.  Data is dropped, which is fine.
        return
    for q in list(client_queues):          # snapshot to avoid mutation during iter
        try:
            state.loop.call_soon_threadsafe(q.put_nowait, data)
        except Exception:
            pass


def _flush_serial_buffer():
    """Discard any stale bytes sitting in the serial input buffer.
    Teensy often sends startup garbage that would cause parse errors."""
    if state.ser is None:
        return
    try:
        state.ser.reset_input_buffer()
        # Also read-and-discard for up to 0.3 s to skip partial lines
        state.ser.timeout = 0.3
        for _ in range(15):
            line = state.ser.readline()
            if not line:
                break
        state.ser.timeout = 1  # restore normal timeout
        logger.info("Serial buffer flushed (startup bytes discarded)")
    except Exception as exc:
        logger.warning("Flush warning: %s", exc)


def serial_reader():
    """Runs in a daemon thread.  Reads serial lines, extracts features,
    predicts gestures, and broadcasts JSON to WebSocket clients."""
    logger.info("═══ Serial reader thread STARTED  →  %s ═══", state.port)

    # Flush stale bytes from Teensy startup
    _flush_serial_buffer()

    sample_count = 0
    last_broadcast_time = 0.0
    last_logged_prediction = ""
    prediction_log_count = 0

    while not state.stop_event.is_set():
        # ── read one line ──────────────────────────────────────────
        try:
            if state.ser is None or not state.ser.is_open:
                logger.warning("Serial port is closed, reader exiting")
                break
            raw_line = state.ser.readline()
            if not raw_line:
                # Timeout — no data received within 1 second
                continue
        except serial.SerialException as exc:
            logger.error("✗ Serial read error: %s", exc)
            _broadcast({
                "raw_value": 0, "prediction": "error", "confidence": 0,
                "window_ready": False, "connected": False,
                "window_count": 0, "timestamp": datetime.now().isoformat(),
                "error": str(exc),
            })
            break
        except OSError as exc:
            logger.error("✗ OS error on serial read (device disconnected?): %s", exc)
            _broadcast({
                "raw_value": 0, "prediction": "error", "confidence": 0,
                "window_ready": False, "connected": False,
                "window_count": 0, "timestamp": datetime.now().isoformat(),
                "error": f"Device disconnected: {exc}",
            })
            break
        except Exception as exc:
            logger.error("✗ Unexpected reader error: %s", exc)
            continue

        # ── parse numeric value ────────────────────────────────────
        decoded = raw_line.decode("utf-8", errors="ignore").strip()
        if not decoded:
            continue

        try:
            value = float(decoded)
        except ValueError:
            logger.debug("Skipping non-numeric line: %r", decoded)
            continue

        sample_count += 1
        state.latest_raw = value

        # Normalize the raw EMG value before putting it into the window
        try:
            normalized_value = float(scaler.transform([[value]])[0][0])
        except Exception as exc:
            logger.error("✗ Scaling error: %s", exc)
            normalized_value = value

        state.window.append(normalized_value)
        state.new_samples += 1
        state.total_samples += 1

        # Log every 500th sample to avoid flooding, but always log the first 5
        if sample_count <= 5 or sample_count % 500 == 0:
            logger.info(
                "Serial sample #%d  raw_line=%r  parsed=%.1f  window=%d/%d",
                sample_count, decoded, value, len(state.window), WINDOW_SIZE,
            )

        # ── current state for this frame ───────────────────────────
        window_ready = len(state.window) >= WINDOW_SIZE
        prediction   = state.last_prediction
        confidence   = state.last_confidence

        # ── run inference when conditions met ──────────────────────
        if window_ready and state.new_samples >= PREDICT_EVERY:
            state.new_samples = 0
            try:
                feats = extract_features(list(state.window))
                df = pd.DataFrame([feats], columns=feature_columns)

                probas   = model.predict_proba(df)[0]
                pred_idx = int(np.argmax(probas))
                state.predictions_history.append(pred_idx)

                # Majority vote over recent predictions
                vote = collections.Counter(state.predictions_history).most_common(1)[0][0]
                prediction = str(label_encoder.inverse_transform([vote])[0])
                confidence = round(float(probas[vote]) * 100, 1)

                state.last_prediction = prediction
                state.last_confidence = confidence

                # Log prediction only if it changes or every 100 cycles to avoid console flood
                prediction_log_count += 1
                if prediction != last_logged_prediction or prediction_log_count >= 100:
                    last_logged_prediction = prediction
                    prediction_log_count = 0
                    logger.info(
                        "🤖 Prediction: %s  confidence=%.1f%%  vote_history=%s",
                        prediction, confidence,
                        [str(label_encoder.inverse_transform([i])[0]) for i in state.predictions_history],
                    )
            except Exception as exc:
                logger.error("✗ Prediction error: %s", exc)

        if not window_ready:
            prediction = "calibrating"
            confidence = 0.0

        # ── broadcast to all WebSocket clients (Throttled to ~40Hz) ─
        current_time = time.time()
        if current_time - last_broadcast_time >= 0.025:
            last_broadcast_time = current_time
            payload = {
                "raw_value":    round(value, 1),
                "prediction":   prediction,
                "confidence":   confidence,
                "window_ready": window_ready,
                "connected":    True,
                "window_count": len(state.window),
                "timestamp":    datetime.now().isoformat(),
            }
            _broadcast(payload)

    # Thread is exiting — mark disconnected, close serial, and notify clients
    state.connected = False
    if state.ser and state.ser.is_open:
        try:
            state.ser.close()
            logger.info("✓ Serial port closed on reader thread exit")
        except Exception as exc:
            logger.warning("Serial close warning on thread exit: %s", exc)
    state.ser = None

    _broadcast({
        "raw_value": 0, "prediction": "disconnected", "confidence": 0,
        "window_ready": False, "connected": False,
        "window_count": 0, "timestamp": datetime.now().isoformat(),
    })
    logger.info("═══ Serial reader thread STOPPED ═══")


# ---------------------------------------------------------------------------
# Demo mode reader (fake EMG data for UI testing)
# ---------------------------------------------------------------------------

DEMO_GESTURES = [
    {"name": "rest",        "baseline": 1854.5, "amp": 15.0},
    {"name": "fist",        "baseline": 1854.5, "amp": 300.0},
    {"name": "thumb",       "baseline": 1854.5, "amp": 180.0},
    {"name": "index",       "baseline": 1854.5, "amp": 120.0},
    {"name": "pinky&ring",  "baseline": 1854.5, "amp": 60.0},
    {"name": "middle",      "baseline": 1854.5, "amp": 150.0},
]


def demo_reader():
    """Generates fake EMG data at ~1000 Hz for testing the UI without hardware."""
    logger.info("═══ DEMO reader thread STARTED (fake EMG) ═══")

    sample_count = 0
    start = time.time()
    last_broadcast_time = 0.0
    last_logged_prediction = ""
    prediction_log_count = 0

    while not state.stop_event.is_set():
        time.sleep(0.001)  # ~1000 Hz

        elapsed = time.time() - start
        # Rotate through gestures every 6 seconds
        gesture_idx = int(elapsed // 6) % len(DEMO_GESTURES)
        gesture = DEMO_GESTURES[gesture_idx]

        # Generate signal oscillating around baseline
        value = gesture["baseline"] + random.gauss(0, gesture["amp"])
        value = round(max(0.0, value), 1)

        sample_count += 1
        state.latest_raw = value

        # Normalize the raw EMG value before putting it into the window
        try:
            normalized_value = float(scaler.transform([[value]])[0][0])
        except Exception as exc:
            logger.error("✗ Demo scaling error: %s", exc)
            normalized_value = value

        state.window.append(normalized_value)
        state.new_samples += 1
        state.total_samples += 1

        # Log every 500th sample to avoid flooding, but always log the first 5
        if sample_count <= 5 or sample_count % 500 == 0:
            logger.info(
                "Demo sample #%d  value=%.1f  gesture_profile=%s  window=%d/%d",
                sample_count, value, gesture["name"], len(state.window), WINDOW_SIZE,
            )

        # ── prediction logic (same as real reader) ────────────────
        window_ready = len(state.window) >= WINDOW_SIZE
        prediction   = state.last_prediction
        confidence   = state.last_confidence

        if window_ready and state.new_samples >= PREDICT_EVERY:
            state.new_samples = 0
            try:
                feats = extract_features(list(state.window))
                df = pd.DataFrame([feats], columns=feature_columns)

                probas   = model.predict_proba(df)[0]
                pred_idx = int(np.argmax(probas))
                state.predictions_history.append(pred_idx)

                vote = collections.Counter(state.predictions_history).most_common(1)[0][0]
                prediction = str(label_encoder.inverse_transform([vote])[0])
                confidence = round(float(probas[vote]) * 100, 1)

                state.last_prediction = prediction
                state.last_confidence = confidence

                # Log prediction only if it changes or every 100 cycles to avoid console flood
                prediction_log_count += 1
                if prediction != last_logged_prediction or prediction_log_count >= 100:
                    last_logged_prediction = prediction
                    prediction_log_count = 0
                    logger.info("🤖 Demo prediction: %s  confidence=%.1f%%", prediction, confidence)
            except Exception as exc:
                logger.error("✗ Demo prediction error: %s", exc)

        if not window_ready:
            prediction = "calibrating"
            confidence = 0.0

        # ── broadcast to all WebSocket clients (Throttled to ~40Hz) ─
        current_time = time.time()
        if current_time - last_broadcast_time >= 0.025:
            last_broadcast_time = current_time
            payload = {
                "raw_value":    round(value, 1),
                "prediction":   prediction,
                "confidence":   confidence,
                "window_ready": window_ready,
                "connected":    True,
                "window_count": len(state.window),
                "timestamp":    datetime.now().isoformat(),
                "demo":         True,
            }
            _broadcast(payload)

    state.connected = False
    _broadcast({
        "raw_value": 0, "prediction": "disconnected", "confidence": 0,
        "window_ready": False, "connected": False,
        "window_count": 0, "timestamp": datetime.now().isoformat(),
    })
    logger.info("═══ DEMO reader thread STOPPED ═══")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/ports")
async def get_ports():
    """List available serial ports, prioritising and labelling Teensy/USB ports."""
    ports = serial.tools.list_ports.comports()
    recommended = []
    others = []

    for p in ports:
        device = p.device or ""
        description = p.description or "n/a"
        manufacturer = p.manufacturer or ""
        product = p.product or ""
        vid = p.vid

        is_teensy = False
        # Teensy VID is typically 0x16C0 (5824). We also check for 'teensy' in descriptors.
        if vid == 5824 or any(
            "teensy" in str(x).lower()
            for x in [manufacturer, product, description, device]
        ):
            is_teensy = True

        is_usb = False
        # Identify generic USB serial devices
        if (
            is_teensy
            or vid is not None
            or any(
                x in device.lower()
                for x in ["usbmodem", "usbserial", "ttyusb", "ttyacm"]
            )
        ):
            is_usb = True

        # Enrich description with vendor/product details if available
        if is_teensy:
            display_desc = f"Teensy ({product or description or 'USB Serial'})"
        elif is_usb:
            display_desc = f"USB Device ({product or description or 'Serial'})"
        else:
            display_desc = description

        port_data = {
            "device": device,
            "description": display_desc,
            "is_teensy": is_teensy,
            "is_usb": is_usb,
            "recommended": is_teensy or is_usb,
        }

        # Filter/relegate system consoles and incoming bluetooth ports
        lower_dev = device.lower()
        if any(
            x in lower_dev
            for x in [
                "bluetooth",
                "incoming-port",
                "debug-console",
                "wlan-debug",
                "cmfbudspro2",
            ]
        ):
            others.append(port_data)
        elif port_data["recommended"]:
            recommended.append(port_data)
        else:
            others.append(port_data)

    # Sort recommended ports: Teensy first, then other USB devices
    recommended.sort(key=lambda x: (not x["is_teensy"], x["device"]))
    # Sort remaining ports alphabetically
    others.sort(key=lambda x: x["device"])

    sorted_ports = recommended + others

    logger.info(
        "GET /api/ports → %d port(s) found (%d recommended)",
        len(sorted_ports),
        len(recommended),
    )
    return {"ports": sorted_ports}


@app.post("/api/connect")
async def connect(req: ConnectRequest):
    """Open a serial connection and start the reader thread."""
    logger.info("POST /api/connect  port=%s  baud=%d", req.port, req.baud)

    if state.connected:
        logger.warning("Already connected — rejecting duplicate connect")
        return JSONResponse({"error": "Already connected. Disconnect first."}, status_code=400)

    try:
        logger.info("Opening serial port %s at %d baud …", req.port, req.baud)
        ser = serial.Serial(req.port, req.baud, timeout=1)
        ser.setDTR(True)
        time.sleep(0.1)  # give Teensy a moment to stabilise
        logger.info("✓ Serial port opened successfully: %s", ser.name)
    except serial.SerialException as exc:
        msg = str(exc)
        if "busy" in msg.lower() or "resource" in msg.lower() or "permission" in msg.lower():
            error_msg = f"Port busy. Close Arduino Serial Monitor first. Detail: {exc}"
        else:
            error_msg = f"Could not open {req.port}. Detail: {exc}"
        logger.error("✗ Serial open failed: %s", error_msg)
        return JSONResponse({"error": error_msg}, status_code=500)

    state.ser = ser
    state.connected = True
    state.port = req.port
    state.demo_mode = False
    state.reset_buffers()
    state.stop_event.clear()
    state.loop = asyncio.get_event_loop()

    state.thread = threading.Thread(target=serial_reader, daemon=True, name="serial-reader")
    state.thread.start()

    logger.info("✓ Connected to %s @ %d baud — reader thread running", req.port, req.baud)
    return {"status": "connected", "port": req.port}


@app.post("/api/disconnect")
async def disconnect():
    """Stop reader thread, close serial port."""
    logger.info("POST /api/disconnect")

    if not state.connected and state.ser is None and not state.demo_mode:
        return JSONResponse({"error": "Not connected."}, status_code=400)

    # Signal the reader thread to stop
    state.stop_event.set()

    # Wait briefly for the thread to exit cleanly
    if state.thread and state.thread.is_alive():
        state.thread.join(timeout=2.0)

    if state.ser and state.ser.is_open:
        try:
            state.ser.close()
            logger.info("✓ Serial port closed")
        except Exception as exc:
            logger.warning("Serial close warning: %s", exc)
    state.ser = None
    state.connected = False
    state.demo_mode = False
    state.port = None

    # Notify WebSocket clients of disconnection
    disc_msg = {
        "raw_value": 0, "prediction": "disconnected", "confidence": 0,
        "window_ready": False, "connected": False,
        "window_count": 0, "timestamp": datetime.now().isoformat(),
    }
    for q in list(client_queues):
        try:
            q.put_nowait(disc_msg)
        except Exception:
            pass

    logger.info("✓ Disconnected")
    return {"status": "disconnected"}


@app.post("/api/demo")
async def start_demo():
    """Start demo mode — generates fake EMG values for UI testing."""
    logger.info("POST /api/demo")

    if state.connected:
        return JSONResponse({"error": "Already connected. Disconnect first."}, status_code=400)

    state.connected = True
    state.port = "DEMO"
    state.demo_mode = True
    state.reset_buffers()
    state.stop_event.clear()
    state.loop = asyncio.get_event_loop()

    state.thread = threading.Thread(target=demo_reader, daemon=True, name="demo-reader")
    state.thread.start()

    logger.info("✓ Demo mode started — generating fake EMG data")
    return {"status": "demo", "port": "DEMO"}


@app.get("/api/test-serial")
async def test_serial():
    """Diagnostic: read 10 raw lines from the currently connected serial port."""
    logger.info("GET /api/test-serial")

    if state.ser is None or not state.ser.is_open:
        return JSONResponse(
            {"error": "No serial port is open. Connect first."},
            status_code=400,
        )

    values = []
    raw_lines = []
    for i in range(10):
        try:
            line = state.ser.readline()
            decoded = line.decode("utf-8", errors="ignore").strip()
            raw_lines.append(decoded)
            try:
                values.append(float(decoded))
            except ValueError:
                values.append(None)
            logger.info("test-serial  line %d: %r → %s", i + 1, decoded, values[-1])
        except Exception as exc:
            raw_lines.append(f"ERROR: {exc}")
            values.append(None)

    return {
        "count": len(values),
        "raw_lines": raw_lines,
        "parsed_values": values,
        "port": state.port,
    }


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """Stream live EMG + prediction data to a browser client."""
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue()
    client_queues.append(q)
    logger.info("⚡ WebSocket client connected  (%d total)", len(client_queues))

    try:
        while True:
            data = await q.get()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
    except Exception as exc:
        logger.warning("WebSocket send error: %s", exc)
    finally:
        if q in client_queues:
            client_queues.remove(q)
        logger.info("WebSocket client removed  (%d remaining)", len(client_queues))

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    print()
    print("=" * 62)
    print("  ⚡  ExoHand Live EMG Gesture Dashboard")
    print("  Open in browser:  http://127.0.0.1:8000")
    print("=" * 62)
    print()
    print("  ⚠  Close the Arduino Serial Monitor before connecting!")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
