# Build Log — ExoHand (Team Orvyn, Group 19, ECTE351)

Reconstructed from file timestamps, KiCad backup snapshots, and code differences across saved versions. This is the honest version of events, including what didn't work.

## Nov 2025 — PCB design starts

The KiCad project (`Exohand_Updated`) is created on 2025-11-20. This is the start of the custom PCB effort, separate from the perfboard build that comes later. Early backup snapshots from 2026-01-09 and 2026-01-15 show the schematic and footprint placement still being worked out.

## Feb 2026 — first signal processing and first firmware

`Filter_signals.py` (2026-02-02) is the first signal-processing script: bandpass filter (20–450 Hz) + 50 Hz notch filter + RMS windowing, run against the public NinaPro benchmark dataset (`S1_A1_E1/E2/E3` emg + restimulus files) rather than the team's own EMG data. This was the validation step — prove the filtering pipeline works against a known public dataset before trusting data collected in-house.

`Exohand_emg_with_filter.ino` (2026-02-16) is the first firmware. It reads three analog channels (flexor, extensor, "extra"), computes RMS over a 40-sample window, and drives a single servo based on which channel has more activity. No classifier yet — this is straight threshold-based assist control. This version is kept in `firmware/archive/` since it was superseded.

## Mar–Apr 2026 — PCB iteration, simulation

`schematic.cir` / `schematic.json` (2026-03-31) and `Exohand_Updated.net` (2026-04-01) are circuit-simulation and netlist exports. Between 2026-04-12 and 2026-04-22 there are five separate KiCad backup snapshots — this was the heaviest period of board-layout iteration, consistent with working through logic/power plane separation and footprint placement issues. All snapshots are kept in `hardware/schematics/archive/Exohand_Updated-backups/`.

## May 2026 — more PCB revisions, web draft, poster

More KiCad backups land on 2026-05-09 and 2026-05-10. The website draft (`ORVYNUpdated.html` and a `-LOCAL` variant) appears on 2026-05-20.

The poster went through three saves in the space of twelve minutes on 2026-05-24 (07:39, 07:45, 07:51) — `ORVYNS_ExoHand_A1_300dpi.pdf`, then `ORVYN's_Poster.pdf`, then `OrvynExoHand_Poster_A1_300dpi.pdf`. All three are different files (checked by hash, not identical), so all three are kept under `docs/posters/`.

On 2026-05-25, `live_predict.py` appears — a script meant to read live EMG over serial from a Teensy, run a pre-trained Random Forest model, and print the predicted gesture with majority-vote smoothing. Its header comment credits "Antigravity AI Assistant" as author. Worth flagging: it looks for model files named `exohand_rf_model.pkl`, `exohand_label_encoder.pkl`, and `exohand_feature_columns.pkl` — none of which exist anywhere in the project. The actual trained artifacts that do exist are `ExoHand_RF_Model.joblib` and `ExoHand_Scaler.joblib`. As saved, this script would not find its model files. A screen recording from the same day (`Screen Recording 2026-05-25 at 5.38.13 PM.mov`) suggests a live demo was attempted around this point.

## Jun 2026 — more PCB iteration, classifier training, perfboard pivot

Three more KiCad backups land on 2026-06-03, three on 2026-06-11, and one on 2026-06-13 — the final push on the PCB before the team moved to a hand-built perfboard for the actual physical build (see below).

`ExoHand_Build_Manual.docx` appears 2026-06-15.

On 2026-06-16, two assembly-guide documents are saved an hour apart — `ExoHand_Perfboard_Assembly_Guide.docx` and `ExoHand_Perfboard_Assembly_Guide_1.docx` (different content, both kept; `_1` archived). This is the point where the project moves from "we designed a custom PCB" to "we are wiring this on perfboard" — likely a fabrication-time or schedule constraint, since the KiCad PCB work continued in parallel rather than being abandoned outright.

The RF classifier notebook exists in two saves: `ExoHand_EMG_Classifier_RF_V2 (1).ipynb` (2026-06-16) then `ExoHand_EMG_Classifier_RF_V2.ipynb` (2026-06-17) — the second is the one kept as current, the first archived. The trained model and scaler (`ExoHand_RF_Model.joblib`, `ExoHand_Scaler.joblib`) are exported the same day the second notebook run finished.

On 2026-06-18, the `AI_Classifier` working folder is assembled: `exohand_assist_control.ino`, `exohand_emg_test.ino`, an updated `Filter_signals.py`, the latest `.kicad_sch`/`.kicad_pcb`, and fresh copies of the joblib model/scaler (a few minutes newer than the root copies — these are the ones treated as current).

On 2026-06-19, `ExoHand_Teensy.ino` appears — the most advanced firmware in the project. It samples EMG at 1 kHz, extracts ten statistical features per window (MAV, RMS, variance, std dev, waveform length, zero-crossing rate, slope sign changes, skewness, kurtosis, IQR), runs a Random Forest classifier **embedded directly in the firmware as decision trees** (`ai_classifier_model.h`), debounces the classification result, and drives four PCA9685 servo channels (pinky&ring, middle, index, thumb) with smoothed motion. It also streams raw EMG and confirmed gestures over UART1 to an ESP32 for a live graph.

**This was the one real gap in the saved history**: `ai_classifier_model.h` is included by `ExoHand_Teensy.ino`/`teensy_final.ino` but never existed anywhere in the project files — the conversion from the trained `.joblib` Random Forest into C arrays was never saved alongside the firmware. **Resolved**: `signal-processing/export_model_to_header.py` now loads `ExoHand_RF_Model.joblib` + `ExoHand_Scaler.joblib` directly and exports the real tree structure (200 trees, 23,024 nodes, 10 features, 6 classes) and the real scaler mean/scale into `firmware/current/ai_classifier_model.h`. Nothing in the header is invented — every threshold, leaf class, and scaler value comes straight from the trained model files. Re-run the script any time the model is retrained.

One real preprocessing mismatch surfaced while building the export script, worth flagging rather than silently fixing: the training notebook scales every raw sample in a window first (`(x - mean) / scale`, a `StandardScaler` fit on the single raw EMG column) and then computes all 10 features from that scaled window. `teensy_final.ino`'s `extractFeatures()` only applies that same scaling to the MAV feature (it has its own `// only MAV was scaled` comment), leaving RMS/Variance/Std/WL computed on raw, unscaled samples. The exported header faithfully reflects the real trained tree thresholds either way — this note is about the firmware's feature-extraction step potentially not matching what the model was trained on, not about the header. Left as-is since fixing it wasn't part of this pass; worth a look if classification accuracy on real hardware looks off.

On 2026-06-20, the last three files land: `ExoHand_ESP32.ino`, `ExoHand_ServoTest.ino`, and the FastAPI live dashboard (`app.py` + templates/static). `ExoHand_ESP32.ino` is a second, ESP32-targeted version of the servo-only test sketch (it uses explicit `Wire.begin(SDA, SCL)` pins, which Teensy code doesn't need but ESP32 does) — its header comment still says "ExoHand_ServoTest.ino", left over from copy-pasting.

At this point in the history, the dashboard backend (`app.py`) was written for a **Teensy 4.1** specifically (also echoed in `web/dashboard/README.md`, `templates/index.html`, and `esp32_bridge.ino`'s comments), while `ExoHand_Teensy.ino`'s own header comment said **Teensy 4.0**. **Resolved**: the project is standardized on **Teensy 4.0** throughout (it's what the firmware header comments, and the actual board footprint in `hardware/schematics/`, agree on). The `app.py` docstring, its always-"Teensy 4.1" port-label bug (`board = "Teensy 4.1" if ... else "Teensy 4.1"`, a no-op ternary — simplified to a plain `"Teensy 4.0"` literal), the dashboard README, `templates/index.html`, and `esp32_bridge.ino`'s comments were all corrected to say 4.0. This section stays as the historical record of why the inconsistency existed; `README.md`/`architecture.md`/`decisions.md` now state Teensy 4.0 with no hedging.

## Recovered from GitHub history (not present in the local Mac file scan)

The repo's existing git history (`AI_Classifier/.git`, already pointed at `github.com/muhammadmapkar/Exohand_Project`) contained 10 commits past the point this reorganization started from. These commits added four files that never existed anywhere in the local `Documents/ORVYN` folder scanned at the start of this job — they were committed straight to GitHub (likely from a different machine or the GitHub web UI) and never synced back to this Mac:

- **`teensy_final.ino`** (444 lines, vs. 303 in `ExoHand_Teensy.ino`) — a more advanced revision of the same flagship firmware. Its own header comment still says `// ExoHand_Teensy.ino`. Adds a `Watchdog_t4` hardware watchdog, EEPROM-backed calibration/baseline persistence (`EEPROM_MAGIC` check), a heartbeat interval, and confidence-gated classification (`CONFIDENCE_THRESHOLD`) on top of everything `ExoHand_Teensy.ino` already did. It still depends on the same missing `ai_classifier_model.h`. Because it's a strict superset/evolution of `ExoHand_Teensy.ino`, it's treated as current and the older file moves to `firmware/archive/`.
- **`esp32_bridge.ino`** — the actual ESP32 WiFi/telemetry sketch that earlier notes (above, and in `decisions.md`/`architecture.md`) said was missing. It runs a WiFi access point (`WiFi.softAP`, SSID `ExoHand_Live`) plus a WebSocket server (port 81, using the `WebSockets` library by Markus Sattler) that bridges serial data from the Teensy (`Serial2`, pins 16/17) straight to a browser. This resolves the gap — the bridge firmware exists, it just wasn't saved into the local project folder.
- **`website.html`** (4262 lines, vs. 3208 in `ORVYNUpdated.html`) — a substantially more developed version of the site: a black/orange "Armory" visual theme, a "Live Rehab" dashboard view (metrics, per-patient goals, control panel), a live EMG chart (Chart.js) presumably fed by `esp32_bridge.ino`'s WebSocket, a camera-based sensor-placement assistant using MediaPipe FaceMesh, and a light Supabase integration. This supersedes `ORVYNUpdated.html`, which moves to `web/archive/`.
- **`exohand_demo.mp4`** — a demo video, added to `media/`.

`web/dashboard/app.py` was also touched in this history (Teensy 4.0 docstring, simpler serial-value parsing), but the copy already pulled from the Mac (which said Teensy 4.1 at the time, and handles comma-separated multi-channel serial lines) is newer than this remote version, so the local copy was kept as current; its 4.1 references were corrected to 4.0 in a later pass (see above).

## Summary of what's "current" vs "archive"

Current: `teensy_final.ino` (flagship classifier firmware, supersedes `ExoHand_Teensy.ino`), `esp32_bridge.ino` (WiFi/WebSocket telemetry bridge), `ExoHand_ESP32.ino`, `ExoHand_ServoTest.ino`, `exohand_assist_control.ino`, `exohand_emg_test.ino`, the 2026-06-17 notebook, the AI_Classifier-folder joblib model/scaler, the latest KiCad sch/pcb, the perfboard guide (non-`_1`), `website.html` (supersedes `ORVYNUpdated.html`), the FastAPI dashboard.

Archived (kept, not deleted): `ExoHand_Teensy.ino` (superseded by `teensy_final.ino`), `Exohand_emg_with_filter.ino` (early single-servo RMS firmware), the duplicate notebook save, root-level joblib duplicates, `ORVYNUpdated.html` and `ORVYNUpdated-LOCAL.html` (superseded by `website.html`), the `_1` perfboard guide, the packaged dashboard zip, every dated KiCad backup snapshot (20 of them), and duplicate dataset copies found in alternate folders.
