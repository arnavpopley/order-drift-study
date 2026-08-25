"""Download NIFTY Smallcap 250 + Midcap 150 daily closes -> data/raw/index_closes.csv.

Uses NSE's daily all-index file (one per trading day). Skips weekends/holidays
(404s), saves incrementally, dedupes at the end.

Usage:
    python -m src.scrape_index --probe        # one day, print rows
    python -m src.scrape_index                # 2020-06-01 .. 2026-06-30
"""

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "index_closes.csv"
WANT = {"nifty smallcap 250", "nifty midcap 150"}
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{}.csv"
SLEEP_S = 2.5
MAX_CONSEC_FAILS = 8


def load_done() -> set[str]:
    if not OUT.exists():
        return set()
    return set(pd.read_csv(OUT)["index_date"].astype(str))


def fetch_day(session: creq.Session, d: date) -> pd.DataFrame | None:
    r = session.get(URL.format(d.strftime("%d%m%Y")),
                    headers={"Referer": "https://www.nseindia.com/"}, timeout=30)
    if r.status_code != 200:
        return None
    df = pd.read_csv(pd.io.common.StringIO(r.text))
    m = df[df["Index Name"].str.lower().isin(WANT)]
    if m.empty:
        return None
    m = m[["Index Name", "Index Date", "Closing Index Value"]].copy()
    m.columns = ["index_name", "index_date", "close"]
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            m["index_date"] = pd.to_datetime(m["index_date"], format=fmt).dt.date.astype(str)
            break
        except (ValueError, TypeError):
            continue
    else:
        raise ValueError(f"unparseable dates: {m['index_date'].tolist()}")
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    s = creq.Session(impersonate="chrome")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    done = load_done()

    d, n_new, fail_streak = start, 0, 0
    while d <= end:
        ds = d.isoformat()
        if ds not in done:
            try:
                rows = fetch_day(s, d)
                if rows is not None:
                    rows.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
                    n_new += len(rows)
                fail_streak = 0
            except Exception as e:
                fail_streak += 1
                print(f"{ds}: error {str(e)[:80]}")
                if fail_streak >= MAX_CONSEC_FAILS:
                    wait = min(60 * fail_streak, 600)
                    print(f"{fail_streak} consecutive failures; cooling down {wait}s, new session")
                    time.sleep(wait)
                    s = creq.Session(impersonate="chrome")
            time.sleep(SLEEP_S)
        d += timedelta(days=1)

    if OUT.exists():
        df = pd.read_csv(OUT).drop_duplicates(["index_name", "index_date"])
        df.sort_values(["index_name", "index_date"]).to_csv(OUT, index=False)
        print(f"done: +{n_new} rows; {len(df)} total "
              f"({df['index_name'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
