import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, iirnotch

SAMPLING_FREQUENCY = 1000
LOWCUT = 20
HIGHCUT = 450
NOTCH_FREQ = 50
QUALITY_FACTOR = 30
RMS_WINDOW_MS = 50
RMS_WINDOW_SAMPLES = int((RMS_WINDOW_MS / 1000) * SAMPLING_FREQUENCY)

def bandpass_filter(signal, fs, lowcut, highcut, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut/nyq, highcut/nyq], btype="band")
    return filtfilt(b, a, signal)

def notch_filter(signal, fs, freq, q):
    nyq = 0.5 * fs
    w0 = freq / nyq
    b, a = iirnotch(w0, q)
    return filtfilt(b, a, signal)

X = []
y = []

pairs = [
    ("S1_A1_E1_emg.csv", "S1_A1_E1_restimulus.csv"),
    ("S1_A1_E2_emg.csv", "S1_A1_E2_restimulus.csv"),
    ("S1_A1_E3_emg.csv", "S1_A1_E3_restimulus.csv")
]

for emg_file, rest_file in pairs:
    emg_df = pd.read_csv(emg_file)
    rest_df = pd.read_csv(rest_file)

    emg_signal = emg_df.iloc[:, 0].astype(float).values
    restimulus = rest_df.iloc[:, 0].values

    emg_filt = bandpass_filter(emg_signal, SAMPLING_FREQUENCY, LOWCUT, HIGHCUT)
    emg_filt = notch_filter(emg_filt, SAMPLING_FREQUENCY, NOTCH_FREQ, QUALITY_FACTOR)

    rectified = np.abs(emg_filt)

    for i in range(0, len(rectified) - RMS_WINDOW_SAMPLES, RMS_WINDOW_SAMPLES):
        rms_val = np.sqrt(np.mean(rectified[i:i+RMS_WINDOW_SAMPLES]**2))
        label = 0 if restimulus[i] == 0 else 1
        X.append(rms_val)
        y.append(label)

X = np.array(X)
y = np.array(y)

dataset = pd.DataFrame({
    "rms": X,
    "label": y
})

dataset = dataset[dataset["rms"] < 0.1]
dataset = dataset.reset_index(drop=True)

dataset.to_csv("exohand_emg_dataset.csv", index=False)

print(dataset.describe())