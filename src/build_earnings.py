"""Extract per-symbol earnings announcement timestamps from our own archive.

Only genuine result announcements count (desc exact-match list below);
exchange clarifications/replies about results do not.

Output: data/processed/earnings_dates.csv (symbol, earnings_dt)
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nse_announcements.csv"
OUT = ROOT / "data" / "processed" / "earnings_dates.csv"

INCLUDE = {
    "financial result updates",
    "financial results updates",
    "publish audited results",
    "consolidated result updates - ifrs",
}


def main() -> None:
    df = pd.read_csv(RAW, usecols=["symbol", "desc", "announced_at"])
    m = df[df["desc"].str.lower().str.strip().isin(INCLUDE)].copy()
    m["earnings_dt"] = pd.to_datetime(m["announced_at"])
    out = m[["symbol", "earnings_dt"]].sort_values(["symbol", "earnings_dt"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"{len(out):,} earnings filings across {out['symbol'].nunique():,} symbols -> {OUT}")


if __name__ == "__main__":
    main()
