"""Cross-validate yfinance closes against NSE bhavcopy (SPEC requirement).

Picks a random sample of symbols x dates from the fetched panel, downloads
the official bhavcopy file for each date, compares closes. yfinance prices
are split/bonus-adjusted while bhavcopy is raw, so small dividend-driven
gaps are expected; large mismatches flag real problems.

Output: results/tables/price_validation.csv

Usage: python -m src.validate_prices [--n-symbols 20] [--dates-per-symbol 4]
"""

import argparse
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parents[1]
PRICES_DIR = ROOT / "data" / "processed" / "prices_raw"
OUT = ROOT / "results" / "tables" / "price_validation.csv"
CACHE = ROOT / "data" / "raw" / "bhavcopy_cache"
TOL = 0.005


def load_panel() -> pd.DataFrame:
    frames = []
    for p in sorted(PRICES_DIR.glob("chunk_*.parquet")):
        try:
            frames.append(pd.read_parquet(p))
        except Exception:
            continue
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def bhavcopy_close(session, d: pd.Timestamp) -> pd.Series | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cpath = CACHE / f"{d:%Y%m%d}.csv"
    if cpath.exists():
        return pd.read_csv(cpath)
    urls = [
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv",
    ]
    for url in urls:
        try:
            r = session.get(url, headers={"Referer": "https://www.nseindia.com/"}, timeout=30)
            if r.status_code != 200:
                continue
            if url.endswith(".zip"):
                zf = zipfile.ZipFile(io.BytesIO(r.content))
                name = zf.namelist()[0]
                raw = zf.read(name).decode("utf-8", errors="replace")
            else:
                raw = r.text
            df = pd.read_csv(io.StringIO(raw))
            df.columns = [str(c).strip() for c in df.columns]
            cols = {c.upper(): c for c in df.columns}
            sym_col = next(cols[k] for k in ("SYMBOL", "TCKRSYMB") if k in cols)
            clsym = next((cols[k] for k in ("SCTYSRS", "SERIES") if k in cols), None)
            close_col = next(cols[k] for k in ("CLSNGPRC", "CLOSE_PRICE") if k in cols)
            out = df.set_index(sym_col)[close_col]
            if clsym:
                ser = df.set_index(sym_col)[clsym].astype(str).str.strip()
                eq = ser.str.upper().isin({"EQ", "BE", "BZ"})
                out = out[eq]
                out.index = [i for i in eq.index[eq]]
            out.index = out.index.astype(str).str.strip()
            out.to_csv(cpath)
            return out
        except Exception:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-symbols", type=int, default=20)
    ap.add_argument("--dates-per-symbol", type=int, default=4)
    args = ap.parse_args()

    panel = load_panel()
    rng = np.random.default_rng(42)
    syms = rng.choice(sorted(panel["symbol"].unique()),
                      size=min(args.n_symbols, panel["symbol"].nunique()), replace=False)

    session = creq.Session(impersonate="chrome")
    rows = []
    cache_days: dict[pd.Timestamp, pd.Series | None] = {}
    for sym in syms:
        sub = panel[panel["symbol"] == sym]
        if len(sub) < 10:
            continue
        picks = sub.sample(min(args.dates_per_symbol, len(sub)), random_state=42)
        for _, r in picks.iterrows():
            d = pd.Timestamp(r["date"])
            if d not in cache_days:
                cache_days[d] = bhavcopy_close(session, d)
                import time as _t
                _t.sleep(0.3)
            bclose = cache_days[d]
            if bclose is None:
                continue
            off = bclose.get(str(sym))
            if off is None or pd.isna(off):
                continue
            diff = abs(float(r["close"]) - float(off)) / float(off)
            rows.append({"symbol": sym, "date": d.date(), "yf_close": round(float(r["close"]), 2),
                         "bhav_close": float(off), "rel_diff": round(diff, 5),
                         "match": diff <= TOL})
            print(rows[-1])

    res = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT, index=False)
    if len(res):
        print(f"\n{res['match'].mean():.0%} match within {TOL:.1%} "
              f"(median rel diff {res['rel_diff'].median():.4%}) -> {OUT}")
    else:
        print("no comparisons made")


if __name__ == "__main__":
    main()
