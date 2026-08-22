"""Classify order-win candidates via Claude API.

Reads data/processed/candidates.csv, batches rows through claude-haiku with a
strict JSON contract, appends raw responses incrementally to
data/processed/classified.jsonl (resume-safe), and merges final labels into
data/processed/classified.csv.

Usage: python -m src.classify [--batch-size 50] [--workers 6]
Requires ANTHROPIC_API_KEY in .env at repo root.
"""

import argparse
import json
import os
import re
import threading
import time
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "processed" / "candidates.csv"
JSONL = ROOT / "data" / "processed" / "classified.jsonl"
OUT = ROOT / "data" / "processed" / "classified.csv"
MODEL = "claude-haiku-4-5"

SYSTEM = """You classify Indian corporate stock-exchange announcements for a research study.

For EACH announcement decide whether it announces that the company has WON /
BEEN AWARDED a new order, contract, work order, Letter of Intent (LoI/LOA),
purchase order, concession, or similar business win.

Rules:
- Mere agreements/MoUs WITHOUT a concrete order value do NOT count -> false,
  unless a definite order/contract is clearly granted.
- Regulatory actions, penalties, court orders, SEBI orders -> false.
- Orders received by a SUBSIDIARY/JV count if the announcement says so.
- "Bagging", "receiving", "securing", "winning" an order/contract -> true.
- If unsure whether a genuine order win was announced -> false.

Extract order_value_inr only when explicitly stated (e.g., "Rs 250 crore",
"INR 42.5 crore"). Convert to rupees: 1 crore = 10,000,000; 1 lakh = 100,000.
No stated value -> null. Never guess.

counterparty_type: "govt" if the client is government/PSU/defense/railways/
ministry/state dept; "private" if a named private company; "unclear" otherwise.

Respond with ONLY a JSON array, one object per input item, same order:
[{"i": <input index>, "is_material_order_win": <true|false>,
  "order_value_inr": <number|null>, "counterparty_type": "<govt|private|unclear>"}]"""


def load_done() -> set[int]:
    done = set()
    if JSONL.exists():
        with JSONL.open() as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done.add(rec["batch_start"])
                except Exception:
                    continue
    return done


def parse_json_array(text: str) -> list | None:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else None
    except json.JSONDecodeError:
        return None


def classify_batch(client: Anthropic, items: list[dict], batch_start: int) -> dict:
    payload = [
        {
            "i": j,
            "desc": str(it["desc"])[:120],
            "company": str(it["company"])[:80],
            "text": str(it["attachment_text"])[:1200],
        }
        for j, it in enumerate(items)
    ]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096 * len(items) // 50 + 1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    arr = parse_json_array(resp.content[0].text)
    if arr is None or len(arr) != len(items):
        raise ValueError(f"bad response for batch {batch_start}: got {arr and len(arr)} items")
    out = []
    for j, lab in enumerate(arr):
        it = items[j]
        out.append(
            {
                **{k: it[k] for k in ("source", "symbol", "company", "isin", "industry",
                                      "desc", "announced_at", "attachment_text", "pdf_url")},
                "is_order_win": bool(lab.get("is_material_order_win")),
                "order_value_inr": lab.get("order_value_inr"),
                "counterparty_type": lab.get("counterparty_type", "unclear"),
            }
        )
    return {"batch_start": batch_start, "labels": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY missing — put it in .env at repo root")
    client = Anthropic(api_key=key)

    df = pd.read_csv(CANDIDATES)
    df["attachment_text"] = df["attachment_text"].fillna("")
    records = df.to_dict("records")
    batches = [
        (start, records[start : start + args.batch_size])
        for start in range(0, len(records), args.batch_size)
    ]
    todo = [(s, b) for s, b in batches if s not in load_done()]
    print(f"{len(batches)} batches total, {len(todo)} remaining")

    lock = threading.Lock()
    errors: list[int] = []

    def work(job):
        start, items = job
        for attempt in range(3):
            try:
                result = classify_batch(client, items, start)
                with lock:
                    with JSONL.open("a") as f:
                        f.write(json.dumps(result) + "\n")
                print(f"batch {start}: ok ({len(result['labels'])})")
                return
            except Exception as e:
                wait = 2 ** attempt * 5
                print(f"batch {start} attempt {attempt + 1} failed: {str(e)[:90]}; retry {wait}s")
                time.sleep(wait)
        with lock:
            errors.append(start)

    threads = []
    sem = threading.Semaphore(args.workers)

    def bounded(job):
        with sem:
            work(job)

    for job in todo:
        t = threading.Thread(target=bounded, args=(job,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    if errors:
        raise SystemExit(f"FAILED batches: {errors[:20]}{'...' if len(errors) > 20 else ''} — rerun to resume")

    rows = []
    if JSONL.exists():
        with JSONL.open() as f:
            for line in f:
                rows.extend(json.loads(line)["labels"])
    merged = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT, index=False)
    print(f"wrote {len(merged):,} classified rows -> {OUT}")
    print(merged["is_order_win"].value_counts().to_string())


if __name__ == "__main__":
    main()
