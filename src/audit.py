"""Classifier hand-audit tooling.

Draw mode:
    python -m src.audit --draw
    -> data/hand/audit_sample.csv with blank hand_label / hand_value /
       hand_counterparty columns. Fill them in by reading attachment_text
       (and the PDF if needed). hand_label: yes/no. hand_value: number in
       INR or blank. Reproducible: fixed seed recorded below.

Score mode:
    python -m src.audit
    -> validates labels, prints confusion matrix + precision/recall +
       value-extraction accuracy, writes results/tables/classifier_audit.csv
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "data" / "processed" / "classified.jsonl"
CLASSIFIED = ROOT / "data" / "processed" / "classified.csv"
SAMPLE = ROOT / "data" / "hand" / "audit_sample.csv"
AUDIT_OUT = ROOT / "results" / "tables" / "classifier_audit.csv"
SEED = 42
N_AUDIT = 100


def load_labels() -> pd.DataFrame:
    if CLASSIFIED.exists():
        return pd.read_csv(CLASSIFIED)
    if JSONL.exists():
        rows = []
        with JSONL.open() as f:
            for line in f:
                rows.extend(json.loads(line)["labels"])
        return pd.DataFrame(rows)
    raise SystemExit("no classification results yet — run src.classify first")


def norm_label(x):
    s = str(x).strip().lower()
    if s in ("yes", "y", "1", "true"):
        return True
    if s in ("no", "n", "0", "false"):
        return False
    return None


def draw() -> None:
    df = load_labels()
    n_available = len(df)
    sample = df.sample(n=min(N_AUDIT, n_available), random_state=SEED).copy()
    sample["hand_label"] = ""
    sample["hand_value"] = ""
    sample["hand_counterparty"] = ""
    cols = [
        "source", "symbol", "company", "desc", "announced_at",
        "attachment_text",
        "is_order_win", "order_value_inr", "counterparty_type",
        "hand_label", "hand_value", "hand_counterparty",
    ]
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    sample[cols].to_csv(SAMPLE, index=False)
    print(f"drew {len(sample)} of {n_available:,} labeled rows (seed={SEED}) -> {SAMPLE}")
    print("fill hand_label (yes/no), hand_value (INR number or blank), "
          "hand_counterparty (govt/private/unclear), then run: python -m src.audit")


def score() -> None:
    if not SAMPLE.exists():
        raise SystemExit(f"{SAMPLE} missing — run --draw first")
    s = pd.read_csv(SAMPLE)
    s["hand_bool"] = s["hand_label"].map(norm_label)
    if s["hand_bool"].isna().any():
        bad = s.loc[s["hand_bool"].isna(), "symbol"].head(5).tolist()
        raise SystemExit(f"unlabeled/incomprehensible hand_label rows (e.g. {bad}) — finish filling")

    model = s["is_order_win"].astype(bool)
    hand = s["hand_bool"].astype(bool)
    tp = int((model & hand).sum())
    fp = int((model & ~hand).sum())
    fn = int((~model & hand).sum())
    tn = int((~model & ~hand).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")

    wins = s[s["hand_bool"] & s["order_value_inr"].notna() & s["hand_value"].notna()].copy()
    val_ok = None
    med_rel_err = None
    if len(wins):
        hv = pd.to_numeric(wins["hand_value"], errors="coerce")
        mv = pd.to_numeric(wins["order_value_inr"], errors="coerce")
        ok = hv.notna() & mv.notna()
        rel = ((mv - hv).abs() / hv)[ok]
        val_ok = float((rel <= 0.05).mean()) * 100
        med_rel_err = float(rel.median())

    cp_mask = s["hand_bool"]
    cp_agree = (
        (s.loc[cp_mask, "counterparty_type"].str.lower()
         == s.loc[cp_mask, "hand_counterparty"].str.lower()).mean() * 100
        if cp_mask.any() and s["hand_counterparty"].notna().all() else None
    )

    print(f"\nn={len(s)}  (seed {SEED})")
    print(f"confusion: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"precision = {precision:.1%}   recall = {recall:.1%}")
    if val_ok is not None:
        print(f"value extraction: {val_ok:.0f}% within ±5%, median |rel err| {med_rel_err:.1%} (n={len(wins)})")
    if cp_agree is not None:
        print(f"counterparty agreement on true wins: {cp_agree:.0f}%")

    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "metric": ["n_sample", "seed", "tp", "fp", "fn", "tn",
                       "precision", "recall", "pct_values_within_5pct",
                       "median_rel_value_error", "counterparty_agreement_pct"],
            "value": [len(s), SEED, tp, fp, fn, tn,
                      round(precision, 4), round(recall, 4),
                      None if val_ok is None else round(val_ok, 1),
                      None if med_rel_err is None else round(med_rel_err, 4),
                      None if cp_agree is None else round(cp_agree, 1)],
        }
    ).to_csv(AUDIT_OUT, index=False)
    print(f"\nwrote {AUDIT_OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", action="store_true")
    args = ap.parse_args()
    draw() if args.draw else score()
