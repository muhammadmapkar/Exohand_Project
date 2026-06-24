# Benchmark dataset — NinaPro

Files in this folder (`S9_A1_E1.mat`, `S9_A1_E2.mat`, `S9_A1_E3.mat`, `S1_A1_E*_emg.csv`, `S1_A1_E*_restimulus.csv`) are **not collected by Team Orvyn.**

They come from the **NinaPro database** (Ninapro: Non-Invasive Adaptive hand Prosthetics), a public benchmark dataset of surface EMG signals used widely in EMG gesture-classification research.

- Subject codes `S1`, `S9` and exercise codes `E1`/`E2`/`E3` are NinaPro's own naming convention, kept as-is.
- Source: https://ninapro.hevs.ch
- Used here to validate the team's filtering and feature-extraction pipeline (`Filter_signals.py`) against a public reference before relying on the team's own collected EMG data.

Cite the original NinaPro publications if reusing this data outside this project.
