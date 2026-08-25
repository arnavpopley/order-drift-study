"""Bulk daily prices for every candidate symbol via yfinance -> prices_raw/.

Downloads .NS OHLCV in chunks; each chunk saved as its own parquet under
data/processed/prices_raw/ so runs are resumable and cheap to retry.
Validation against NSE bhavcopy happens separately (src/validate_prices.py).

Usage: python -m src.fetch_prices [--chunk 100]
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "processed" / "candidates.csv"
OUTDIR = ROOT / "data" / "processed" / "prices_raw"
START, END = "2020-06-01", "2026-07-01"


def fetch_chunk(tickers: list[str]) -> pd.DataFrame:
    df = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    rows = []
    if isinstance(df.columns, pd.MultiIndex):
        for t in tickers:
            if t not in df.columns.get_level_values(0):
                continue
            sub = df[t][["Close", "Volume"]].dropna(how="all")
            if sub.empty:
                continue
            sub = sub.reset_index().rename(columns={"Date": "date", "Close": "close", "Volume": "volume"})
            sub.insert(0, "symbol", t.removesuffix(".NS"))
            rows.append(sub[["symbol", "date", "close", "volume"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=100)
    args = ap.parse_args()

    symbols = sorted(pd.read_csv(CANDIDATES)["symbol"].unique())
    OUTDIR.mkdir(parents=True, exist_ok=True)
    done_files = {p.stem for p in OUTDIR.glob("chunk_*.parquet")}
    todo_idx = [i for i in range(0, len(symbols), args.chunk)
                if f"chunk_{i // args.chunk:04d}" not in done_files]
    print(f"{len(symbols)} symbols in {len(range(0, len(symbols), args.chunk))} chunks, "
          f"{len(todo_idx)} to fetch")

    for n, i in enumerate(todo_idx):
        chunk_syms = symbols[i : i + args.chunk]
        chunk = [f"{t}.NS" for t in chunk_syms]
        try:
            part = fetch_chunk(chunk)
        except Exception as e:
            print(f"[{n + 1}/{len(todo_idx)}] chunk {i}: ERROR {str(e)[:80]}", flush=True)
            time.sleep(10)
            continue
        got = set(part["symbol"]) if not part.empty else set()
        part.to_parquet(OUTDIR / f"chunk_{i // args.chunk:04d}.parquet",
                        engine="pyarrow", index=False)
        missing = [t[:-3] for t in chunk if t[:-3] not in got]
        print(f"[{n + 1}/{len(todo_idx)}] chunk {i}: +{len(part)} rows, "
              f"{len(missing)} empty", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
