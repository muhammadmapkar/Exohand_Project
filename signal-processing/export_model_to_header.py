#!/usr/bin/env python3
"""
export_model_to_header.py

Exports the trained ExoHand Random Forest classifier and its EMG scaler
into a plain C/C++ header (`ai_classifier_model.h`) that the Teensy 4.0
firmware (`firmware/current/teensy_final.ino`) can compile against directly.
No external libraries, no dynamic allocation -- just const arrays and a
small tree-walk inference helper.

Source of truth (loaded as-is, nothing hand-edited or invented):
  - signal-processing/ExoHand_RF_Model.joblib   (sklearn RandomForestClassifier)
  - signal-processing/ExoHand_Scaler.joblib     (sklearn StandardScaler)

These were produced by ExoHand_EMG_Classifier_RF_V2.ipynb, which:
  1. Fits StandardScaler on the single raw 'EMG' column (one feature).
  2. Builds sliding windows (size 30) of the *scaled* EMG signal.
  3. Extracts 10 features per window, in this exact order:
       MAV, RMS, Variance, Std, WL, ZCR, SSC, Skew, Kurtosis, IQR
  4. Trains RandomForestClassifier(n_estimators=200) on those 10 features.

That feature order/scaling is what this script mirrors -- NOT
signal-processing/live_predict.py, whose extract_features() uses a
different, unrelated 8-feature set (mean/std/max/min/range/rms/mav/wl) and
loads .pkl filenames that don't exist in this repo. live_predict.py is a
stale/disconnected script; ExoHand_RF_Model.joblib was trained by the
notebook's pipeline, so the notebook is the authoritative reference for
matching feature order and scaling, per the actual model file.

Usage:
    python3 export_model_to_header.py [--out PATH]

Default output path: ../firmware/current/ai_classifier_model.h
(relative to this script's directory).
"""

import argparse
import datetime
import os
import sys

try:
    import joblib
    import numpy as np
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install joblib numpy scikit-learn")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "ExoHand_RF_Model.joblib")
SCALER_PATH = os.path.join(SCRIPT_DIR, "ExoHand_Scaler.joblib")

# Must match RF_NODES field order expected by firmware (feature/threshold/left/right/leaf_class).
LEAF_MARKER = -1  # sklearn's tree_.children_left/right use -1 (TREE_LEAF) to mark leaves.


def load_artifacts():
    if not os.path.exists(MODEL_PATH):
        sys.exit(f"CRITICAL: model file not found: {MODEL_PATH}")
    if not os.path.exists(SCALER_PATH):
        sys.exit(f"CRITICAL: scaler file not found: {SCALER_PATH}")
    rf = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return rf, scaler


def validate_scaler(scaler):
    """The scaler must be a single-feature StandardScaler fit on raw EMG.
    Refuse to export if this assumption doesn't hold -- do not invent values."""
    if not hasattr(scaler, "mean_") or not hasattr(scaler, "scale_"):
        sys.exit("CRITICAL: scaler object has no mean_/scale_ -- not a fitted StandardScaler.")
    if scaler.n_features_in_ != 1:
        sys.exit(
            f"CRITICAL: expected a single-feature scaler (raw EMG), got "
            f"n_features_in_={scaler.n_features_in_}. Refusing to export "
            f"mismatched assumptions -- update this script's scaler handling first."
        )
    return float(scaler.mean_[0]), float(scaler.scale_[0])


def flatten_tree(tree, node_offset):
    """Walk one sklearn DecisionTreeClassifier's internal tree_ structure and
    return a list of (feature, threshold, left, right, leaf_class) tuples,
    indices already offset into the shared flat array."""
    children_left = tree.children_left
    children_right = tree.children_right
    feature = tree.feature
    threshold = tree.threshold
    value = tree.value  # shape (n_nodes, 1, n_classes) -- class counts, classes_ order

    nodes = []
    for i in range(tree.node_count):
        is_leaf = children_left[i] == LEAF_MARKER
        if is_leaf:
            leaf_class = int(np.argmax(value[i][0]))
            nodes.append((-1, 0.0, -1, -1, leaf_class))
        else:
            nodes.append((
                int(feature[i]),
                float(threshold[i]),
                int(children_left[i]) + node_offset,
                int(children_right[i]) + node_offset,
                -1,
            ))
    return nodes


def build_flat_forest(rf):
    """Concatenate every tree's nodes into one flat array, recording each
    tree's root offset into that array (matches firmware's RF_TREE_ROOTS /
    RF_NODES[idx].left/.right addressing scheme)."""
    all_nodes = []
    tree_roots = []
    for estimator in rf.estimators_:
        offset = len(all_nodes)
        tree_roots.append(offset)  # root of each sklearn tree is always local index 0
        all_nodes.extend(flatten_tree(estimator.tree_, offset))
    return all_nodes, tree_roots


def render_header(rf, scaler_mean, scaler_scale, all_nodes, tree_roots, feature_names, class_names):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    n_features = len(feature_names)
    n_classes = len(class_names)
    n_trees = len(tree_roots)
    n_nodes = len(all_nodes)

    lines = []
    lines.append("// ai_classifier_model.h")
    lines.append("// AUTO-GENERATED by signal-processing/export_model_to_header.py")
    lines.append(f"// Generated: {now}")
    lines.append("// Source: signal-processing/ExoHand_RF_Model.joblib + ExoHand_Scaler.joblib")
    lines.append("// Do not hand-edit. Regenerate with:")
    lines.append("//   python3 signal-processing/export_model_to_header.py")
    lines.append("//")
    lines.append(f"// Model: RandomForestClassifier, n_estimators={n_trees}, n_nodes={n_nodes}")
    lines.append(f"// Features ({n_features}, in order): {', '.join(feature_names)}")
    lines.append(f"// Classes ({n_classes}, leaf_class index order): {', '.join(class_names)}")
    lines.append("//")
    lines.append("// Scaler: single-feature StandardScaler fit on raw EMG (NOT per-feature).")
    lines.append("// Per the training notebook, every raw window sample is scaled via")
    lines.append("// (x - SCALER_MEAN) / SCALER_SCALE *before* the 10 features above are")
    lines.append("// computed. teensy_final.ino currently only applies this scaling to the")
    lines.append("// MAV feature (see its own '// only MAV was scaled' comment) -- that is")
    lines.append("// a pre-existing firmware approximation, not something this script")
    lines.append("// changes. See docs/build-log.md for the full note.")
    lines.append("#ifndef AI_CLASSIFIER_MODEL_H")
    lines.append("#define AI_CLASSIFIER_MODEL_H")
    lines.append("")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append(f"#define RF_NUM_FEATURES {n_features}")
    lines.append(f"#define RF_NUM_CLASSES  {n_classes}")
    lines.append(f"#define RF_NUM_TREES    {n_trees}")
    lines.append(f"#define RF_NUM_NODES    {n_nodes}")
    lines.append("")
    lines.append("// EMG scaler (StandardScaler fit on the raw EMG column). Exact values")
    lines.append("// from ExoHand_Scaler.joblib -- guarded so an existing #define in the")
    lines.append("// .ino (if any) takes precedence instead of conflicting.")
    lines.append("#ifndef SCALER_MEAN")
    lines.append(f"#define SCALER_MEAN  {scaler_mean!r}f")
    lines.append("#endif")
    lines.append("#ifndef SCALER_SCALE")
    lines.append(f"#define SCALER_SCALE {scaler_scale!r}f")
    lines.append("#endif")
    lines.append("")
    lines.append("// Feature order each tree's `feature` index refers into:")
    lines.append("static const char* const RF_FEATURE_NAMES[RF_NUM_FEATURES] = {")
    lines.append("  " + ", ".join(f'"{f}"' for f in feature_names))
    lines.append("};")
    lines.append("")
    lines.append("static const char* const RF_CLASS_NAMES[RF_NUM_CLASSES] = {")
    lines.append("  " + ", ".join(f'"{c}"' for c in class_names))
    lines.append("};")
    lines.append("")
    lines.append("// One flat node array shared by all RF_NUM_TREES trees.")
    lines.append("// feature == -1  -> leaf node, read leaf_class directly.")
    lines.append("// feature != -1  -> internal node: go left if feat[feature] <= threshold, else right.")
    lines.append("typedef struct {")
    lines.append("  int8_t  feature;     // 0..RF_NUM_FEATURES-1, or -1 for a leaf")
    lines.append("  int8_t  leaf_class;  // 0..RF_NUM_CLASSES-1 if leaf, else -1")
    lines.append("  int16_t left;        // index into RF_NODES, or -1 for a leaf")
    lines.append("  int16_t right;       // index into RF_NODES, or -1 for a leaf")
    lines.append("  float   threshold;")
    lines.append("} RFNode;")
    lines.append("")
    lines.append("static const RFNode RF_NODES[RF_NUM_NODES] = {")
    row = []
    for i, (feature, threshold, left, right, leaf_class) in enumerate(all_nodes):
        row.append(f"{{{feature},{leaf_class},{left},{right},{threshold!r}f}}")
        if len(row) == 4:
            lines.append("  " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("  " + ", ".join(row) + ",")
    lines.append("};")
    lines.append("")
    lines.append("// Root node index (into RF_NODES) for each of the RF_NUM_TREES trees.")
    lines.append("static const int16_t RF_TREE_ROOTS[RF_NUM_TREES] = {")
    for i in range(0, len(tree_roots), 16):
        chunk = tree_roots[i:i + 16]
        lines.append("  " + ", ".join(str(r) for r in chunk) + ",")
    lines.append("};")
    lines.append("")
    lines.append("// Standalone inference helper (majority vote across all trees).")
    lines.append("// teensy_final.ino defines its own classify()/predictTree() against the")
    lines.append("// arrays above; this function is provided so the header is usable on its")
    lines.append("// own in another sketch, without name collisions against that code.")
    lines.append("static inline int rf_classify_standalone(const float feat[RF_NUM_FEATURES], float* confidence_out) {")
    lines.append("  int votes[RF_NUM_CLASSES] = {0};")
    lines.append("  for (int t = 0; t < RF_NUM_TREES; t++) {")
    lines.append("    int idx = RF_TREE_ROOTS[t];")
    lines.append("    while (RF_NODES[idx].feature != -1) {")
    lines.append("      if (feat[RF_NODES[idx].feature] <= RF_NODES[idx].threshold)")
    lines.append("        idx = RF_NODES[idx].left;")
    lines.append("      else")
    lines.append("        idx = RF_NODES[idx].right;")
    lines.append("    }")
    lines.append("    votes[RF_NODES[idx].leaf_class]++;")
    lines.append("  }")
    lines.append("  int best = 0;")
    lines.append("  for (int c = 1; c < RF_NUM_CLASSES; c++) if (votes[c] > votes[best]) best = c;")
    lines.append("  if (confidence_out) *confidence_out = (float)votes[best] / RF_NUM_TREES;")
    lines.append("  return best;")
    lines.append("}")
    lines.append("")
    lines.append("#endif // AI_CLASSIFIER_MODEL_H")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=os.path.join(SCRIPT_DIR, "..", "firmware", "current", "ai_classifier_model.h"),
        help="Output header path (default: firmware/current/ai_classifier_model.h)",
    )
    args = parser.parse_args()

    rf, scaler = load_artifacts()
    scaler_mean, scaler_scale = validate_scaler(scaler)

    feature_names = list(getattr(rf, "feature_names_in_", []))
    if not feature_names:
        sys.exit(
            "CRITICAL: model has no feature_names_in_ -- it wasn't trained on a "
            "named DataFrame, so feature order can't be verified. Refusing to "
            "guess the order."
        )
    class_names = [str(c) for c in rf.classes_]

    all_nodes, tree_roots = build_flat_forest(rf)

    header_text = render_header(
        rf, scaler_mean, scaler_scale, all_nodes, tree_roots, feature_names, class_names
    )

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(header_text)

    print(f"Wrote {out_path}")
    print(f"  n_estimators={len(tree_roots)}  n_nodes={len(all_nodes)}  n_features={len(feature_names)}  n_classes={len(class_names)}")
    print(f"  features: {feature_names}")
    print(f"  classes:  {class_names}")
    print(f"  scaler:   mean={scaler_mean!r} scale={scaler_scale!r}")
    print(f"  file size: {os.path.getsize(out_path)} bytes")


if __name__ == "__main__":
    main()
