"""NSE corporate announcements scraper -> data/raw/nse_announcements.csv.

Primary announcement source (see SPEC.md amendments: promoted over BSE after
BSE API proved geo-blocked). Pulls Reg 30 filings month by month via
/api/corporate-announcements for equities + SME boards, appending each month
to disk so an interrupted run resumes cheaply.

Usage:
    python -m src.scrape_nse --probe            # one recent month, print rows
    python -m src.scrape_nse                    # full 2021-01..2026-06
    python -m src.scrape_nse --start 2022,1 --end 2026,6
"""

import argparse
import csv
import random
import time
from datetime import date, timedelta
from pathlib import Path

from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = RAW / "nse_announcements.csv"
DEFAULT_START = (2021, 1)
DEFAULT_END = (2026, 6)

BASE = "https://www.nseindia.com"
API = f"{BASE}/api/corporate-announcements"
REFERER = f"{BASE}/companies-listing/corporate-filings-announcements"
INDEXES = ["equities", "sme"]
POLITE_SLEEP_S = 3.0
MAX_RETRIES = 5

FIELDS = [
    "source",
    "symbol",
    "company",
    "isin",
    "industry",
    "desc",
    "announced_at",
    "attachment_text",
    "pdf_url",
]


def month_chunks(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield date(y, m, 1), date(ny, nm, 1) - timedelta(days=1)
        y, m = ny, nm


def new_session() -> creq.Session:
    s = creq.Session(impersonate="chrome")
    s.get(BASE, timeout=30)
    return s


def fetch_month(session: creq.Session, day_from: date, day_to: date, index: str):
    params = {
        "index": index,
        "from_date": day_from.strftime("%d-%m-%Y"),
        "to_date": day_to.strftime("%d-%m-%Y"),
    }
    headers = {"Referer": REFERER, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"}
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(API, params=params, headers=headers, timeout=90)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                last_err = f"unexpected payload type {type(data).__name__}"
            elif r.status_code in (401, 403, 404):
                last_err = f"status {r.status_code}"
            else:
                last_err = f"status {r.status_code}"
        except Exception as e:
            last_err = str(e)[:100]
        wait = 5 * (attempt + 1) + random.uniform(0, 2)
        print(f"  retry {attempt + 1}/{MAX_RETRIES} ({last_err}); sleeping {wait:.0f}s")
        time.sleep(wait)
        session = new_session()
    raise RuntimeError(f"giving up on {index} {day_from}..{day_to}: {last_err}")


def normalize(row: dict, index: str) -> dict:
    pdf = row.get("attchmntFile") or ""
    return {
        "source": f"NSE-{index}",
        "symbol": (row.get("symbol") or "").strip(),
        "company": (row.get("sm_name") or "").strip(),
        "isin": (row.get("sm_isin") or "").strip(),
        "industry": (row.get("smIndustry") or "").strip(),
        "desc": (row.get("desc") or "").strip(),
        "announced_at": (row.get("sort_date") or "").strip(),
        "attachment_text": (row.get("attchmntText") or "").replace("\r\n", " ").replace("\n", " ").strip(),
        "pdf_url": pdf.strip() if pdf.lower() != "none" else "",
    }


def append_rows(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    is_new = not OUT.exists()
    with OUT.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerows(rows)


def dedupe_all() -> int:
    if not OUT.exists():
        return 0
    seen = set()
    rows = []
    with OUT.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for row in reader:
            key = (row["source"], row["symbol"], row["announced_at"], row["desc"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(OUT)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=f"{DEFAULT_START[0]},{DEFAULT_START[1]}")
    ap.add_argument("--end", default=f"{DEFAULT_END[0]},{DEFAULT_END[1]}")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    session = new_session()
    sy, sm = (int(x) for x in args.start.split(","))
    ey, em = (int(x) for x in args.end.split(","))

    if args.probe:
        d = fetch_month(session, date(2024, 6, 1), date(2024, 6, 30), "equities")
        print(f"rows: {len(d)}")
        for row in d[:3]:
            print(normalize(row, "equities"))
        return

    total_new = 0
    for day_from, day_to in month_chunks((sy, sm), (ey, em)):
        for index in INDEXES:
            try:
                data = fetch_month(session, day_from, day_to, index)
            except RuntimeError as e:
                print(f"{day_from:%Y-%m} {index}: FAILED - {e}")
                continue
            rows = [normalize(r, index) for r in data]
            append_rows(rows)
            total_new += len(rows)
            print(f"{day_from:%Y-%m} {index}: {len(rows)} rows (cumulative {total_new})")
            time.sleep(POLITE_SLEEP_S + random.uniform(0, 2))

    kept = dedupe_all()
    print(f"done: {total_new} rows appended; {kept} unique rows in {OUT}")


if __name__ == "__main__":
    main()
