"""BSE announcements archive scraper -> data/raw/bse_announcements.csv.

Prototype for Day 1. Pulls Reg 30 corporate filings in monthly chunks from the
BSE announcement API backing www.bseindia.com/corporates/ann.html, saving
incrementally so interruptions are cheap.

Usage:
    python -m src.scrape_bse --probe                 # one page, print rows
    python -m src.scrape_bse                         # full 2021-01..2026-06
    python -m src.scrape_bse --start 2022-01 --end 2026-06
"""

import argparse
import csv
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = RAW / "bse_announcements.csv"
DEFAULT_START = (2021, 1)
DEFAULT_END = (2026, 6)

API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubPageGetData/w"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/corporates/ann.html",
    "Accept": "application/json",
}
PAGE_SIZE_HINT = 50
POLITE_SLEEP_S = 1.0
MAX_RETRIES = 4

FIELDS = [
    "source",
    "scrip_cd",
    "company",
    "headline",
    "announced_at",
    "category",
    "pdf_url",
]


def month_chunks(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        first = date(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        last = date(ny, nm, 1) - timedelta(days=1)
        yield first, last
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_page(session: requests.Session, day_from: date, day_to: date, pageno: int):
    params = {
        "pageno": pageno,
        "strCat": "-1",
        "strPrevDate": day_to.strftime("%Y%m%d"),
        "strScrip": "",
        "strSearch": "P",
        "strtDt": day_from.strftime("%Y%m%d"),
        "endDate": day_to.strftime("%Y%m%d"),
    }
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(API_URL, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 429):
                wait = 5 * (attempt + 1)
                print(f"  blocked ({r.status_code}); sleeping {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            wait = 3 * (attempt + 1)
            print(f"  error {e}; retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"giving up on {day_from}..{day_to} page {pageno}")


def normalize(row: dict) -> dict:
    attachment = (row.get("ATTACHMENTNAME") or "").strip()
    return {
        "source": "BSE",
        "scrip_cd": (row.get("SCRIP_CD") or "").strip(),
        "company": (row.get("SLONGNAME") or "").strip(),
        "headline": (row.get("NEWSSUB") or row.get("HEADLINE") or "").strip(),
        "announced_at": (row.get("NEWS_SUBMISSION_DT") or "").strip(),
        "category": (row.get("CATEGORYNAME") or "").strip(),
        "pdf_url": (
            f"https://attachments.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}"
            if attachment
            else ""
        ),
    }


def append_rows(rows: list[dict]) -> None:
    is_new = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerows(rows)


def probe(session: requests.Session) -> None:
    data = fetch_page(session, date(2024, 6, 3), date(2024, 6, 4), 1)
    table = data.get("Table") or []
    print(f"keys: {list(data.keys())}")
    print(f"rows on page: {len(table)}")
    for row in table[:5]:
        print(normalize(row))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=",".join(map(str, DEFAULT_START)))
    ap.add_argument("--end", default=",".join(map(str, DEFAULT_END)))
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)

    if args.probe:
        probe(session)
        return

    sy, sm = (int(x) for x in args.start.split(","))
    ey, em = (int(x) for x in args.end.split(","))
    total = 0
    for day_from, day_to in month_chunks((sy, sm), (ey, em)):
        pageno = 1
        while True:
            data = fetch_page(session, day_from, day_to, pageno)
            table = data.get("Table") or []
            if not table:
                break
            rows = [normalize(r) for r in table]
            append_rows(rows)
            total += len(rows)
            print(f"{day_from:%Y-%m}: page {pageno} (+{len(rows)}, total {total})")
            if len(rows) < PAGE_SIZE_HINT:
                break
            pageno += 1
            time.sleep(POLITE_SLEEP_S)
        time.sleep(POLITE_SLEEP_S)

    dedupe_all()
    print(f"done: {total} raw rows appended; deduped file at {OUT}")


def dedupe_all() -> None:
    if not OUT.exists():
        return
    seen = set()
    lines = []
    with OUT.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for row in reader:
            key = (row["scrip_cd"], row["announced_at"], row["headline"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(row)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(lines)
    tmp.replace(OUT)


if __name__ == "__main__":
    main()
