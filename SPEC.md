# SPEC — Post-Announcement Drift in Indian Order-Win Announcements

**Status:** FROZEN 2026-08-21 (Day 0). Any deviation from this document requires a
dated note in the "Dated amendments" section at the bottom. No new analysis after Day 5.

## Research question

Do Indian small/midcap stocks underreact to order/contract-win announcements,
leaving exploitable post-announcement drift (Bernard-Thomas style) after the
initial reaction?

## Event definition

- **Event:** order / contract win announcements — BSE/NSE Reg 30 filings.
- **T=0 rule:** filing timestamp before 15:30 IST → same trading day;
  at or after 15:30 IST → next trading day.

## Sample

- **Period:** Jan 2021 – Jun 2026.
- **Universe:** BSE/NSE listed equities, prior-day market cap ₹500 cr – ₹25,000 cr.
  Per the AMFI semi-annual categorisation (Jul–Dec 2026 cut-off: smallcap <
  ₹33,433 cr), this band lies entirely within the AMFI smallcap segment; the
  study is therefore framed as a smallcap study, not "small/midcap".
- **Materiality:** order value ≥ 10% of prior-day market cap.
- **Exclusions:**
  - events within ±2 days of earnings announcements;
  - events within ±30 days of splits/bonuses;
  - banks/NBFCs (no "orders");
  - stocks with median daily traded value < ₹50 lakh.
- **Target:** 200–400 clean events. Proceed at ≥150. Kill criteria per day in README.

## Abnormal return models

1. **PRIMARY — market-adjusted:** AR = stock return − NIFTY Smallcap 250 return.
2. Market model (alpha/beta estimated over [−130, −11]).
3. IIMA four-factor model.

Robustness: primary spec rerun with NIFTY Midcap 150 as the market proxy
(size-mismatch check; see amendment dated 2026-08-21).

## Test specifications

- **PRIMARY SPEC: CAAR[+2,+20]**, bootstrap 95% CI, 10,000 resamples.
- **Secondary:**
  - CAR[0,+1] announcement reaction (mean, median, % positive);
  - CAAR[+2,+60];
  - BMP standardized test on the announcement window (formal check);
  - consistency of story across all three AR models.

## Pre-committed slices (ONLY these)

- market-cap terciles
- order-size terciles
- liquidity terciles

Each reported as CAAR by tercile with CIs. Nothing else gets sliced.

## Strategy test

Calendar-time portfolio: each day hold all stocks that announced within the past
20 trading days, equal weight; regress daily portfolio excess returns on four
factors; Newey-West alpha (20 lags). Report gross alpha and net of 50 bps and
75 bps per side round-trip costs. State which survive.

## Robustness (pre-committed)

- Winsorize ARs at 1%, rerun primary.
- Drop top-10 largest-CAR events, rerun (single-driver check).
- Split sample pre/post Jan 2024 (regime check).

## Data sources

- **Announcements:** BSE announcements archive (category filters + timestamps),
  NSE archive as fallback. Monthly chunks, retries, incremental saves.
- **Classification:** Claude API batch classification of headlines (+ first-page
  text when vague), JSON-only output. Hand-audit of n=100 random sample:
  precision AND recall recorded in paper. If precision < ~90%: tighten prompt
  once, rerun, re-audit.
- **Prices:** NSE bhavcopy closes as primary source; Groww API historical candles
  as fallback/cross-source; yfinance `.NS` as tertiary. Validation rule: any
  ticker where two sources disagree on a close is investigated or dropped.
  Cross-check ≥15 random tickers across two independent sources before analysis.
- **Index:** NIFTY Smallcap 250 daily series (primary); NIFTY Midcap 150 for
  the robustness variant. Source: niftyindices.com historical closes or NSE
  daily all-index file.
- **Market caps / corporate actions:** prior-day mcap from price × shares out
  (yfinance/NSE); earnings dates from announcement archive; splits/bonuses from
  NSE corporate actions file.

Note: bhavcopy/broker-API closes are raw (unadjusted). The ±30d split/bonus
exclusion defuses adjustment risk; residual dividend effects over event windows
are accepted and noted in limitations.

## Repo contract

- Layout: `data/raw` (immutable scrape dumps) · `data/hand` (hand labels, committed)
  · `data/processed` (built tables) · `src` · `notebooks` · `results` · `paper`.
- `run_all.py` rebuilds every figure and table in `results/` from raw data.
  If a number is in the paper, a script produced it.
- API keys live in `.env`, never committed.

## Definition of done

Repo where `run_all.py` regenerates every number from raw data; 12–15 page PDF;
stated classifier precision/recall; stated final event count; one frozen primary
result with CI; limitations section naming: market-adjusted primary spec,
LLM-classification error rate, no delisting adjustment, price-source validation
coverage, single-regime sample.

## Standing rules (all 10 days)

1. End every data day with a 30-minute random-row eyeball (20 rows minimum).
2. Any choice arising mid-sprint not covered here: take the simpler option and
   add one dated line below. That audit trail is what makes speed defensible.

---

## Dated amendments

*(append only — format: `YYYY-MM-DD — what changed and why`)*

- 2026-08-21 — SPEC frozen. Price source hierarchy set to bhavcopy > Groww > yfinance.
- 2026-08-21 — Scraper prototype: `api.bseindia.com` returns HTML block page to
  requests AND curl_cffi (chrome TLS impersonation, warmed cookies); NSE API
  times out. Pattern suggests IP/geo-level block from this network. Day 1 plan:
  (a) verify site loads in local browser → if yes use Playwright real-browser
  session; (b) if browser also fails → India-IP route (VPN or cheap IN VPS);
  (c) NSE archive retry as alternate host.
- 2026-08-21 — VPN session (note: exits via Singapore datacenter IP). BSE API
  still blocked; **NSE promoted to primary announcement source** — new endpoint
  `/api/corporate-announcements?index=equities|sme` verified working with
  month-sized chunks, no pagination cap, full depth back to ≥Jan 2020. Fields
  include symbol, timestamp, category desc, first-page text, PDF URL. Scraper:
  `src/scrape_nse.py` (curl_cffi chrome impersonation + cookie warmup). BSE
  kept as fallback only.
- 2026-08-21 — Classifier engine switched from Anthropic to **Gemini
  (gemini-2.5-flash, free tier)**: batches of 200, ~115 calls total, JSON-mode
  output, same prompt contract and audit plan. Hand-audit n=100 unchanged.
- 2026-08-21 — Universe relabeled **AMFI smallcap** (Jul–Dec 2026 cut-off:
  smallcap < ₹33,433 cr ⇒ entire ₹500–25,000 cr band is smallcap; no midcaps
  in sample). Primary benchmark switched NIFTY Midcap 150 → **NIFTY Smallcap
  250** to size-match the universe; Midcap-150 variant demoted to robustness.
  Amended before any returns were computed. Model name in classifier updated
  gemini-2.5-flash → gemini-3.6-flash (old model retired for new API keys).
- 2026-08-26 — Price panel: yfinance adjusted closes chosen as bulk primary
  (bhavcopy retained for validation + raw-close needs); validated n=52 obs,
  median |diff| 0.54%, residuals fully explained by dividends/splits
  (results/tables/price_validation.csv). Materiality market caps must use
  **raw close × shares-outstanding-as-of-event**: shares_current divided by
  the product of split/bonus factors from corp_actions with ex-date after
  the event. Unparsed action ratios get flagged for manual resolution.
