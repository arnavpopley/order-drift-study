"""Pre-filter raw announcements into an order-win candidate pool.

Recall-first: a broad keyword net over desc + first 400 chars of text, minus
desc categories that are definitionally regulatory (never order wins). The LLM
classifier downstream owns precision; this stage only exists to keep Claude
cost and volume sane.

Output: data/processed/candidates.csv
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nse_announcements.csv"
OUT = ROOT / "data" / "processed" / "candidates.csv"

REGULATORY_DESC = (
    r"(?i)^action\(s\)? (initiated|taken) or orders? passed$"
    r"|adjudication|sebi order|penalty|settlement order|show cause"
)

SURVEILLANCE_DESC = r"(?i)^(spurt in volume|price movement)$"

KEYWORDS = (
    r"(?i)\b(order|orders|contract|contracts|award|awarded|awarding|bagged|"
    r"secured|wins?|work order|letter of intent|\bloi\b|\bloa\b|"
    r"purchase order|agreement|agreements|mou|memorandum of understanding|"
    r"concession|tender|empanelment|rate contract|framework agreement)\b"
)


def main() -> None:
    df = pd.read_csv(RAW, parse_dates=["announced_at"])
    df["attachment_text"] = df["attachment_text"].fillna("")
    n0 = len(df)

    reg_mask = df["desc"].str.contains(REGULATORY_DESC, regex=True, na=False)
    surv_mask = df["desc"].str.contains(SURVEILLANCE_DESC, regex=True, na=False)
    df = df[~(reg_mask | surv_mask)]
    n1 = len(df)

    hay = df["desc"].fillna("") + " || " + df["attachment_text"].str.slice(0, 400)
    kw_mask = hay.str.contains(KEYWORDS, regex=True, na=False)
    out = df[kw_mask].drop_duplicates(subset=["symbol", "announced_at", "attachment_text"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"raw rows:          {n0:,}")
    print(f"minus regulatory:  -{n0 - n1:,}  -> {n1:,}")
    print(f"keyword matches:   {kw_mask.sum():,}")
    print(f"candidates (dedup):{len(out):,} -> {OUT}")
    print("\ntop descs in pool:")
    print(out["desc"].value_counts().head(10).to_string())
    print("\ndate span:", out["announced_at"].min(), "->", out["announced_at"].max())


if __name__ == "__main__":
    main()
