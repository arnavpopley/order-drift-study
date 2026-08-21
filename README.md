# Order-Win Drift Study

Event study: do Indian small/midcaps underreact to order-win announcements
(Reg 30 filings), leaving exploitable post-announcement drift?

Pre-analysis plan: see [SPEC.md](SPEC.md). It is frozen; deviations get dated
notes there.

## Quickstart

```bash
uv sync
cp .env.example .env   # add ANTHROPIC_API_KEY for classification day
python run_all.py      # rebuilds everything in results/
```

## Pipeline stages (run_all.py)

1. `scrape` — BSE/NSE announcement archive → `data/raw/`
2. `classify` — Claude API + hand audit → `data/processed/classified.csv`
3. `events` — ticker match, materiality, exclusions, T=0 → `data/processed/events.csv`
4. `prices` — bhavcopy/Groww/yfinance panel → `data/processed/prices.parquet`
5. `analysis` — CARs, CAARs, bootstrap CIs, BMP, slices, calendar-time portfolio
6. `figures` — CAAR plot and all paper figures → `results/`

Each stage skips if its output exists; delete the output to force a rerun.

## Kill criteria

- **Day 1:** <3 years of raw announcements by evening → shrink window to
  2022–2026. <2 years → stop and rethink (~150 clean events is viability floor).
- **Day 2:** <150 clean events after screens → drop materiality threshold to
  7.5% or extend window; document in SPEC.md amendments.
- **Classifier audit:** precision <90% after one prompt tightening → manual
  triage of ambiguous classes.
- **Price validation:** any ticker where two sources disagree on a close →
  investigate or drop.
