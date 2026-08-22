"""Rebuild every result in results/ from raw data.

Stages run in order; each skips itself if its output already exists so the
pipeline is resumable across days. Delete a stage's output to force a rerun.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
STAGES = [
    # (module, output that proves the stage completed)
    ("src.scrape_nse", "data/raw/nse_announcements.csv"),
    ("src.classify", "data/processed/classified.csv"),
    ("src.build_events", "data/processed/events.csv"),
    ("src.build_prices", "data/processed/prices.parquet"),
    ("src.analysis", "results/tables/caar_primary.csv"),
    ("src.figures", "results/figures/caar_plot.png"),
]


def done(output: str) -> bool:
    return (ROOT / output).exists()


def main() -> None:
    for module, output in STAGES:
        if done(output):
            print(f"[skip] {module} -> {output} exists")
            continue
        print(f"[run ] {module}")
        subprocess.run([sys.executable, "-m", module], check=True, cwd=ROOT)
    print("All stages up to date.")


if __name__ == "__main__":
    main()
