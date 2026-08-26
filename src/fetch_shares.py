"""Fetch current shares outstanding for every candidate symbol via yfinance
-> data/processed/shares_outstanding.csv.

Used as prior-day market cap proxy: mcap_t-1 = close_t-1 * shares_current.
Historical share-count drift is a documented limitation (SPEC.md).

Usage: python -m src.fetch_shares [--rate 0.4]
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "processed" / "candidates.csv"
OUT = ROOT / "data" / "processed" / "shares_outstanding.csv"


def load_done() -> dict[str, float]:
    if OUT.exists():
        df = pd.read_csv(OUT)
        return dict(zip(df["symbol"], df["shares"]))
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=0.4, help="seconds between requests")
    args = ap.parse_args()

    symbols = sorted(pd.read_csv(CANDIDATES)["symbol"].unique())
    done = load_done()
    todo = [s for s in symbols if s not in done]
    print(f"{len(symbols)} symbols, {len(todo)} to query", flush=True)

    out_path_exists = OUT.exists()
    n_new = 0
    for i, sym in enumerate(todo):
        try:
            info = yf.Ticker(f"{sym}.NS").info or {}
            sh = info.get("sharesOutstanding")
        except Exception:
            sh = None
        if sh:
            mode = "a" if out_path_exists else "w"
            header = not out_path_exists or OUT.stat().st_size == 0
            with OUT.open(mode) as f:
                if header:
                    f.write("symbol,shares\n")
                f.write(f"{sym},{sh}\n")
            out_path_exists = True
            n_new += 1
        if (i + 1) % 100 == 0:
            print(f"[{i + 1}/{len(todo)}] (+{n_new} new)", flush=True)
        time.sleep(args.rate)

    total = len(load_done())
    print(f"done: {n_new} fetched this run; {total} total known")


if __name__ == "__main__":
    main()
