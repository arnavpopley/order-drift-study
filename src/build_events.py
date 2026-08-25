"""Build the preliminary event table from classified order-win announcements.

Price-independent stage: T=0 assignment, dedup/contamination rule, and the
bank-NBFC / earnings / split-bonus exclusion screens. Materiality (needs
market caps) and liquidity (needs traded value) are applied later in
src/build_prices.py -> events_final.csv.

Waterfall counts print at every stage (paper Table 1).

Input : data/processed/classified.csv  (is_order_win == True rows)
Output: data/processed/events_prelim.csv
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIED = ROOT / "data" / "processed" / "classified.csv"
INDEX = ROOT / "data" / "raw" / "index_closes.csv"
EARNINGS = ROOT / "data" / "processed" / "earnings_dates.csv"
CORP_ACTIONS = ROOT / "data" / "raw" / "corp_actions.csv"
OUT = ROOT / "data" / "processed" / "events_prelim.csv"

FIN_INDUSTRIES = {"banks", "finance", "financial institution", "finance - housing"}
SPLIT_BONUS_RX = r"(?i)split|sub[- ]?divis|bonus|face value|consolidation"
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST", "IL", "GB", "MF"}  # equity-ish NSE series
CONTAMINATION_TRADING_DAYS = 60
EARNINGS_BUFFER_TDAYS = 2
CORPACTION_BUFFER_DAYS = 30

waterfall: list[tuple[str, int]] = []


def step(name: str, n: int) -> None:
    waterfall.append((name, n))
    print(f"{name:<45} {n:>7,}")


def trading_calendar() -> list[pd.Timestamp]:
    idx = pd.read_csv(INDEX)
    days = sorted(pd.to_datetime(idx.loc[idx["index_name"] == "Nifty Smallcap 250", "index_date"]))
    return [d for d in days]


def assign_t0(ts: pd.Series, cal: list[pd.Timestamp], cal_pos: dict[pd.Timestamp, int]) -> pd.Series:
    def resolve(t):
        day = pd.Timestamp(t.date())
        if t.hour < 15 or (t.hour == 15 and t.minute < 30):
            base = day
        else:
            base = day
            pos = cal_pos.get(day)
            if pos is not None:
                return cal[min(pos + 1, len(cal) - 1)]
        if base not in cal_pos:
            nxt = [c for c in cal if c >= base]
            base = nxt[0] if nxt else cal[-1]
        return base
    return ts.apply(resolve)


def main() -> None:
    df = pd.read_csv(CLASSIFIED)
    wins = df[df["is_order_win"] == True].copy()  # noqa: E712
    step("classified order-win announcements", len(wins))

    wins["announced_at"] = pd.to_datetime(wins["announced_at"])
    wins = wins.drop_duplicates(subset=["symbol", "announced_at", "attachment_text"])

    cal = trading_calendar()
    cal_ts = [pd.Timestamp(c) for c in cal]
    cal_pos = {c: i for i, c in enumerate(cal_ts)}

    wins["t0"] = assign_t0(wins["announced_at"], cal_ts, cal_pos)

    n_before = len(wins)
    wins = wins.drop_duplicates(subset=["symbol", "t0"], keep="first")
    step("after one-event-per-symbol-day dedup", len(wins))
    print(f"   (dropped {n_before - len(wins)} same-day duplicates)")

    ind = wins.get("industry")
    if ind is not None:
        fin_mask = ind.fillna("").str.lower().str.strip().isin(FIN_INDUSTRIES)
        wins = wins[~fin_mask]
    step("after bank/NBFC industry exclusion", len(wins))

    wins = wins.sort_values(["symbol", "announced_at"]).reset_index(drop=True)
    t0_pos = wins["t0"].map(cal_pos)
    sym = wins["symbol"]
    last_pos_by_symbol, keep_mask = {}, []
    for s, p in zip(sym, t0_pos):
        lp = last_pos_by_symbol.get(s)
        if lp is None or p - lp > CONTAMINATION_TRADING_DAYS:
            last_pos_by_symbol[s] = p
            keep_mask.append(True)
        else:
            keep_mask.append(False)
    wins = wins.loc[keep_mask]
    step(f"after {CONTAMINATION_TRADING_DAYS}-trading-day contamination rule", len(wins))

    earn = pd.read_csv(EARNINGS)
    earn["earnings_dt"] = pd.to_datetime(earn["earnings_dt"])
    earn["e_pos"] = earn["earnings_dt"].apply(
        lambda t: cal_pos.get(pd.Timestamp(t.date()), None))
    earn = earn.dropna(subset=["e_pos"])
    earn_by_symbol = {s: g["e_pos"].tolist() for s, g in earn.groupby("symbol")}

    def near_earnings(row):
        p = row["t0_pos"]
        for ep in earn_by_symbol.get(row["symbol"], []):
            if abs(p - ep) <= EARNINGS_BUFFER_TDAYS:
                return True
        return False

    wins["t0_pos"] = wins["t0"].map(cal_pos)
    wins = wins[~wins.apply(near_earnings, axis=1)]
    step(f"after +/-{EARNINGS_BUFFER_TDAYS} trading-day earnings exclusion", len(wins))

    ca = pd.read_csv(CORP_ACTIONS)
    ca = ca[ca["series"].isin(EQUITY_SERIES)]
    ca = ca[ca["subject"].str.contains(SPLIT_BONUS_RX, regex=True, na=False)]
    ca["ex_dt"] = pd.to_datetime(ca["ex_date"], format="%d-%b-%Y", errors="coerce")
    ca = ca.dropna(subset=["ex_dt"])
    ca_by_symbol = {s: g["ex_dt"].tolist() for s, g in ca.groupby("symbol")}

    def near_corp_action(row):
        t0d = row["t0"]
        for ex in ca_by_symbol.get(row["symbol"], []):
            if abs((t0d - ex).days) <= CORPACTION_BUFFER_DAYS:
                return True
        return False

    wins = wins[~wins.apply(near_corp_action, axis=1)]
    step(f"after +/-{CORPACTION_BUFFER_DAYS} day split/bonus exclusion", len(wins))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wins.to_csv(OUT, index=False)
    print(f"\nevents_prelim -> {OUT}")
    print("\nwaterfall (paper Table 1):")
    for name, n in waterfall:
        print(f"  {name}: {n:,}")


if __name__ == "__main__":
    main()
