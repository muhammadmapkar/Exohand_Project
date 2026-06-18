#!/usr/bin/env python3
"""
ExoHand Live EMG Gesture Prediction script.
Reads raw EMG values from a serial port (Teensy 4.0), processes them
using a sliding window, extracts statistical features, runs inference
via a pre-trained Random Forest model, and performs majority vote smoothing.

Author: Antigravity AI Assistant
"""

import os
import sys
import time
import random
import collections
import warnings

# Suppress warnings from version mismatches in unpickled scikit-learn estimators
warnings.filterwarnings("ignore", category=UserWarning)

# Ensure dependencies are available before importing
try:
    import serial
    import serial.tools.list_ports
    import numpy as np
    import pandas as pd
    import joblib
except ImportError as e:
    print(f"Error importing dependency: {e}")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)

# Warn user about Arduino Serial Monitor (Requirement 11)
print("\n" + "=" * 65)
print(" IMPORTANT NOTICE:")
print(" Please make sure to CLOSE the Arduino Serial Monitor or any other")
print(" software using the serial port before running this script.")
print(" Only one application can access the serial port at a time.")
print("=" * 65 + "\n")

# Determine script directory to locate the model files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# File candidate names for robust loading (Requirement 1 & Context)
MODEL_FILES = ["exohand_rf_model.pkl", "exohand_rf_model_v1.pkl"]
ENCODER_FILES = ["exohand_label_encoder.pkl", "exohand_label_encoder_v1.pkl"]
COLUMNS_FILES = ["exohand_feature_columns.pkl", "exohand_feature_columns_v1.pkl"]


def load_pickle_file(candidates, description):
    """Searches for pickle files in script and current directory and loads them."""
    # Check script directory first
    for candidate in candidates:
        full_path = os.path.join(SCRIPT_DIR, candidate)
        if os.path.exists(full_path):
            try:
                data = joblib.load(full_path)
                print(f"Successfully loaded {description} from: {candidate}")
                return data
            except Exception as ex:
                print(f"Error loading {candidate}: {ex}")
    
    # Fallback: check current directory
    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                data = joblib.load(candidate)
                print(f"Successfully loaded {description} from current dir: {candidate}")
                return data
            except Exception as ex:
                print(f"Error loading {candidate}: {ex}")
                
    print(f"CRITICAL ERROR: Could not find {description}. Tried: {candidates}")
    sys.exit(1)


# Load the trained model, label encoder, and feature column list (Do not retrain)
model = load_pickle_file(MODEL_FILES, "Random Forest Model")
label_encoder = load_pickle_file(ENCODER_FILES, "Label Encoder")
feature_columns = load_pickle_file(COLUMNS_FILES, "Feature Columns List")


class SimulatedSerial:
    """
    Mock Serial class to simulate EMG signal data in real-time.
    Used for testing model inference and windowing without Teensy hardware connected.
    """
    def __init__(self):
        self.is_open = True
        self.start_time = time.time()
        # Simulated states of hand gestures to produce realistic EMG signals
        self.states = [
            {"gesture": "rest", "mean": 15, "std": 3},
            {"gesture": "fist", "mean": 450, "std": 45},
            {"gesture": "thumb", "mean": 280, "std": 30},
            {"gesture": "index", "mean": 180, "std": 20},
            {"gesture": "open hand", "mean": 90, "std": 10}
        ]
        print("\n--- Running in SIMULATION MODE ---")
        print("Simulating real-time EMG values (50 Hz)...\n")

    def readline(self):
        """Simulate reading one line containing a numeric value with a 20ms delay."""
        time.sleep(0.02) # ~50 Hz sampling rate
        elapsed = time.time() - self.start_time
        
        # Cycle through different gesture profiles every 8 seconds
        state_idx = int(elapsed // 8) % len(self.states)
        state = self.states[state_idx]
        
        # Generate raw-like EMG voltage amplitude using Gaussian distribution
        raw_val = random.gauss(state["mean"], state["std"])
        raw_val = max(5, raw_val)  # EMG signals are rectified (non-negative)
        
        return f"{raw_val:.1f}\n".encode('utf-8')

    def close(self):
        self.is_open = False


def select_serial_port():
    """
    Lists available hardware serial ports and prompts the user to select one.
    Also provides a built-in simulation mode option for testing.
    """
    ports = list(serial.tools.list_ports.comports())
    
    print("Available Serial Devices:")
    for idx, p in enumerate(ports):
        print(f"  [{idx + 1}] {p.device} - {p.description}")
        
    print(f"  [{len(ports) + 1}] Enter port manually")
    print(f"  [{len(ports) + 2}] Run in SIMULATION mode (no hardware required)")
    
    while True:
        try:
            choice = input(f"\nSelect an option (1-{len(ports) + 2}): ").strip()
            if not choice:
                continue
            
            val = int(choice)
            if 1 <= val <= len(ports):
                return ports[val - 1].device
            elif val == len(ports) + 1:
                return input("Enter Serial Port path (e.g. /dev/cu.usbmodem14101): ").strip()
            elif val == len(ports) + 2:
                return "SIMULATE"
        except ValueError:
            # If the user typed the port directly (e.g., '/dev/ttyACM0')
            if choice:
                return choice


def extract_features(win_values):
    """
    Extracts the 8 required time-domain statistical features from the sliding window.
    Features: mean, std, max, min, range, rms, mav, waveform_length.
    """
    win = np.array(win_values)
    
    mean_val = np.mean(win)
    std_val = np.std(win)
    max_val = np.max(win)
    min_val = np.min(win)
    range_val = max_val - min_val
    rms_val = np.sqrt(np.mean(np.square(win)))
    mav_val = np.mean(np.abs(win))
    waveform_len_val = np.sum(np.abs(np.diff(win)))
    
    features = {
        'mean': mean_val,
        'std': std_val,
        'max': max_val,
        'min': min_val,
        'range': range_val,
        'rms': rms_val,
        'mav': mav_val,
        'waveform_length': waveform_len_val
    }
    return features


def main():
    # 1. Select and open serial port
    port_choice = select_serial_port()
    
    ser = None
    if port_choice == "SIMULATE":
        ser = SimulatedSerial()
    else:
        print(f"Connecting to serial port '{port_choice}' at 115200 baud...")
        try:
            # Connect to Teensy 4.0 (Requirement 2 & 9)
            ser = serial.Serial(port_choice, 115200, timeout=1.0)
            # Toggle DTR/RTS to reset Teensy (standard serial behavior)
            ser.setDTR(True)
            time.sleep(0.1)
        except serial.SerialException as se:
            print(f"\nCRITICAL SERIAL ERROR: Could not open port {port_choice}.")
            print(f"Details: {se}")
            print("Please make sure the port is correct and not in use by Arduino Serial Monitor.")
            sys.exit(1)

    # Sliding Window configuration (Requirement 4, 5 & 6)
    WINDOW_SIZE = 25
    PREDICT_EVERY_N = 5
    VOTE_HISTORY_SIZE = 5
    
    window = collections.deque(maxlen=WINDOW_SIZE)
    predictions_history = collections.deque(maxlen=VOTE_HISTORY_SIZE)
    new_samples_counter = 0

    print(f"\nListening for EMG data. Window filling status: [0/{WINDOW_SIZE}]...")
    
    try:
        while True:
            # Read line from serial (Requirement 3)
            line = ser.readline()
            if not line:
                # Read timed out, check again
                continue
                
            try:
                # Decode line and clean whitespace
                decoded_line = line.decode('utf-8').strip()
                if not decoded_line:
                    continue
                # Parse numeric value
                emg_val = float(decoded_line)
            except (UnicodeDecodeError, ValueError):
                # Ignore corrupt transmission/noise lines safely (Requirement 9)
                continue
            
            # Add to sliding window
            window.append(emg_val)
            new_samples_counter += 1
            
            # Print window filling progress initially
            if len(window) < WINDOW_SIZE:
                if len(window) % 5 == 0 or len(window) == WINDOW_SIZE - 1:
                    print(f"Filling window... [{len(window)}/{WINDOW_SIZE}] samples")
                continue
                
            # Once window is full and we collected the required new samples, run prediction (Requirement 5)
            if new_samples_counter >= PREDICT_EVERY_N:
                new_samples_counter = 0
                
                # Extract features from the sliding window
                feats = extract_features(window)
                
                # Format features into a pandas DataFrame matching columns exactly
                df = pd.DataFrame([feats], columns=feature_columns)
                
                # Compute predictions probability (Requirement 7)
                probabilities = model.predict_proba(df)[0]
                
                # Get index of the class with highest probability
                pred_idx = np.argmax(probabilities)
                
                # Append predicted index to sliding history queue
                predictions_history.append(pred_idx)
                
                # Majority vote smoothing over the history (Requirement 6)
                most_common = collections.Counter(predictions_history).most_common(1)
                smoothed_pred_idx = most_common[0][0]
                
                # Translate class index to text gesture label
                gesture_label = label_encoder.inverse_transform([smoothed_pred_idx])[0]
                
                # Retrieve prediction confidence for the smoothed gesture
                confidence_percent = probabilities[smoothed_pred_idx] * 100.0
                
                # Print output matching format: Gesture: thumb | Confidence: 82.4% | EMG: 14 (Requirement 8)
                # Raw EMG value is printed as int if possible for cleaner look
                emg_val_formatted = int(emg_val) if emg_val.is_integer() else emg_val
                print(f"Gesture: {gesture_label:<12} | Confidence: {confidence_percent:5.1f}% | EMG: {emg_val_formatted}")
                
    except KeyboardInterrupt:
        # Safe shut down on Ctrl+C (Requirement 10)
        print("\n\nCtrl+C detected. Safely exiting...")
    except Exception as e:
        print(f"\nAn unexpected error occurred during execution: {e}")
    finally:
        # Guarantee closure of serial port (Requirement 9 & 10)
        if ser is not None:
            try:
                ser.close()
                print("Serial connection closed successfully.")
            except Exception as e:
                print(f"Error while closing serial port: {e}")
        print("Program finished.")


if __name__ == "__main__":
    main()
