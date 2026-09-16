"""Build the final event sample from prelim events + prices + shares.

Applies the mechanical screens (SPEC): market cap in [Rs 500cr, Rs 25,000cr],
order value >= 10% of prior-day mcap, median daily traded value >= Rs 50 lakh
over the estimation window, and a non-null machine order value. Prior-day
market cap uses the RAW bhavcopy close at t-1 x current shares outstanding.

Writes data/processed/events_final.csv and prints the screen waterfall.

Usage: python -m src.build_prices
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.validate_prices import bhavcopy_close  # reuse raw-close fetcher
from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parents[1]
PRICES_DIR = ROOT / "data" / "processed" / "prices_raw"
SHARES = ROOT / "data" / "processed" / "shares_outstanding.csv"
EVT_IN = ROOT / "data" / "processed" / "events_prelim.csv"
EVT_OUT = ROOT / "data" / "processed" / "events_final.csv"
T0_OFF = -1
EST_LO, EST_HI = -130, -11
MCAP_LO, MCAP_HI = 5e9, 2.5e11
MAT_FLOOR = 0.10
LIQ_FLOOR = 5e6


def load_panel() -> pd.DataFrame:
    frames = []
    for p in sorted(PRICES_DIR.glob("chunk_*.parquet")):
        try:
            frames.append(pd.read_parquet(p))
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ev = pd.read_csv(EVT_IN)
    ev["t0"] = pd.to_datetime(ev["t0"])
    shares = pd.read_csv(SHARES).set_index("symbol")["shares"]
    panel = load_panel()
    panel["date"] = pd.to_datetime(panel["date"])
    session = creq.Session(impersonate="chrome")

    rows = []
    for _, r in ev.iterrows():
        sym = r["symbol"]
        if sym not in shares.index:
            continue
        sub = panel[panel["symbol"] == sym].sort_values("date").set_index("date")
        if len(sub) < 60:
            continue
        pos = sub.index.searchsorted(r["t0"], side="right") - 1
        if pos < max(-EST_LO, 11):
            continue
        t1 = sub.index[pos + T0_OFF]
        raw = bhavcopy_close(session, t1)
        close_t1 = float(raw.get(sym)) if raw is not None and sym in raw.index else float(sub["close"].iloc[pos + T0_OFF])
        mcap = close_t1 * float(shares[sym])
        est = sub.iloc[EST_LO:EST_HI + 1]
        liq = (est["close"] * est["volume"]).median()
        ov = r["order_value_inr"]
        rows.append({
            "symbol": sym, "t0": r["t0"].date(), "company": r["company"],
            "order_value_inr": ov, "mcap_prior": mcap,
            "materiality_ratio": (ov / mcap) if pd.notna(ov) and mcap else np.nan,
            "median_daily_value": liq,
        })

    df = pd.DataFrame(rows)
    n0 = len(df)
    print(f"prelim events with shares+price: {n0}")
    df = df[df["order_value_inr"].notna()]
    print(f"  - dropped: no machine order value    -> {len(df)}")
    df = df[(df["mcap_prior"] >= MCAP_LO) & (df["mcap_prior"] <= MCAP_HI)]
    print(f"  - mcap band [500cr,25000cr]          -> {len(df)}")
    df = df[df["materiality_ratio"] >= MAT_FLOOR]
    print(f"  - materiality >= 10%                 -> {len(df)}")
    df = df[df["median_daily_value"] >= LIQ_FLOOR]
    print(f"  - liquidity >= 50 lakh/day           -> {len(df)}")
    EVT_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVT_OUT, index=False)
    print(f"-> {EVT_OUT}")


if __name__ == "__main__":
    main()
