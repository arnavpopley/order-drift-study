"""NSE corporate-actions scraper -> data/raw/corp_actions.csv.

Monthly chunks over the sample window; used for the +/-30 day split/bonus
exclusion screen. Equity series only at analysis time; raw dump kept complete.

Usage:
    python -m src.scrape_corp_actions            # 2020-06 .. 2026-06
    python -m src.scrape_corp_actions --probe
"""

import argparse
import csv
import random
import time
from datetime import date, timedelta
from pathlib import Path

from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "corp_actions.csv"
API = "https://www.nseindia.com/api/corporates-corporateActions"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-corporate-actions"
POLITE_SLEEP_S = 3.0
MAX_RETRIES = 5

FIELDS = ["symbol", "company", "series", "subject", "ex_date", "rec_date",
          "face_val", "isin", "purpose_extra"]


def month_chunks(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield date(y, m, 1), date(ny, nm, 1) - timedelta(days=1)
        y, m = ny, nm


def new_session() -> creq.Session:
    s = creq.Session(impersonate="chrome")
    s.get("https://www.nseindia.com", timeout=30)
    return s


def fetch_month(session: creq.Session, day_from: date, day_to: date):
    params = {
        "index": "equities",
        "from_date": day_from.strftime("%d-%m-%Y"),
        "to_date": day_to.strftime("%d-%m-%Y"),
    }
    headers = {"Referer": REFERER, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"}
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(API, params=params, headers=headers, timeout=90)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                last = f"payload type {type(data).__name__}"
            else:
                last = f"status {r.status_code}"
        except Exception as e:
            last = str(e)[:90]
        wait = 5 * (attempt + 1) + random.uniform(0, 2)
        print(f"  retry {attempt + 1} ({last}); {wait:.0f}s")
        time.sleep(wait)
        session = new_session()
    raise RuntimeError(f"giving up {day_from}..{day_to}: {last}")


def normalize(row: dict) -> dict:
    return {
        "symbol": (row.get("symbol") or "").strip(),
        "company": (row.get("comp") or "").strip(),
        "series": (row.get("series") or "").strip(),
        "subject": (row.get("subject") or "").strip(),
        "ex_date": (row.get("exDate") or "").strip(),
        "rec_date": (row.get("recDate") or "").strip(),
        "face_val": (row.get("faceVal") or "").strip(),
        "isin": (row.get("isin") or "").strip(),
        "purpose_extra": "",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020,6")
    ap.add_argument("--end", default="2026,6")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    session = new_session()
    sy, sm = (int(x) for x in args.start.split(","))
    ey, em = (int(x) for x in args.end.split(","))

    if args.probe:
        d = fetch_month(session, date(2024, 6, 1), date(2024, 6, 30))
        print(f"rows: {len(d)}")
        for row in d[:3]:
            print(normalize(row))
        return

    total = 0
    for day_from, day_to in month_chunks((sy, sm), (ey, em)):
        try:
            data = fetch_month(session, day_from, day_to)
        except RuntimeError as e:
            print(f"{day_from:%Y-%m}: FAILED - {e}")
            continue
        rows = [normalize(r) for r in data]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if not OUT.exists() or OUT.stat().st_size == 0:
                w.writeheader()
            w.writerows(rows)
        total += len(rows)
        print(f"{day_from:%Y-%m}: {len(rows)} rows (cumulative {total})")
        time.sleep(POLITE_SLEEP_S + random.uniform(0, 2))

    seen, rows = set(), []
    if OUT.exists():
        with OUT.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            for row in reader:
                key = (row["symbol"], row["ex_date"], row["subject"])
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        tmp = OUT.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerows(rows)
        tmp.replace(OUT)
    print(f"done: {total} appended; {len(rows)} unique -> {OUT}")


if __name__ == "__main__":
    main()
