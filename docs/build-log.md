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

**This is the one real gap in the saved history**: `ai_classifier_model.h` is included by `ExoHand_Teensy.ino` but does not exist anywhere in the project files. It was almost certainly generated by converting the trained `.joblib` Random Forest into C arrays (a fairly standard step for embedding sklearn models on a microcontroller), but that conversion script and its output were never saved alongside the firmware. As committed here, `ExoHand_Teensy.ino` will not compile on its own — this is flagged rather than silently fixed, per the "don't invent features" rule.

On 2026-06-20, the last three files land: `ExoHand_ESP32.ino`, `ExoHand_ServoTest.ino`, and the FastAPI live dashboard (`app.py` + templates/static). `ExoHand_ESP32.ino` is a second, ESP32-targeted version of the servo-only test sketch (it uses explicit `Wire.begin(SDA, SCL)` pins, which Teensy code doesn't need but ESP32 does) — its header comment still says "ExoHand_ServoTest.ino", left over from copy-pasting. No standalone ESP32 WiFi/telemetry sketch was found, despite the Teensy firmware and the project README describing ESP32-C3 wireless telemetry as part of the design — that side of the bridge wasn't saved (or wasn't finished) separately from this servo test.

The dashboard backend (`app.py`) is written for a **Teensy 4.1** specifically, while `ExoHand_Teensy.ino`'s own header comment says **Teensy 4.0**. Both are kept as-is; this inconsistency is noted rather than resolved, since the actual board used wasn't independently verifiable from the files.

## Summary of what's "current" vs "archive"

Current: `ExoHand_Teensy.ino` (flagship classifier firmware), `ExoHand_ESP32.ino`, `ExoHand_ServoTest.ino`, `exohand_assist_control.ino`, `exohand_emg_test.ino`, the 2026-06-17 notebook, the AI_Classifier-folder joblib model/scaler, the latest KiCad sch/pcb, the perfboard guide (non-`_1`), `ORVYNUpdated.html`, the FastAPI dashboard.

Archived (kept, not deleted): `Exohand_emg_with_filter.ino` (early single-servo RMS firmware), the duplicate notebook save, root-level joblib duplicates, `ORVYNUpdated-LOCAL.html`, the `_1` perfboard guide, the packaged dashboard zip, every dated KiCad backup snapshot (20 of them), and duplicate dataset copies found in alternate folders.
