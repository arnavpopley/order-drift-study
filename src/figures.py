"""Figure generation (CAAR path with bootstrap CI = headline plot).

Loads the price panel + NIFTY Smallcap 250 index, builds market-adjusted ARs
for every event via src.analysis, and draws the cumulative average abnormal
return over [-10, +60] with a 10,000-resample bootstrap 95% band.

Runs on the *final* events file if present, else the prelim set (smoke test
before materiality screen is applied).

Usage: python -m src.figures
"""

import numpy as np
import pandas as pd

from src import analysis as A

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
PRICES_DIR = ROOT / "data" / "processed" / "prices_raw"
INDEX = ROOT / "data" / "raw" / "index_closes.csv"
EVT_FINAL = ROOT / "data" / "processed" / "events_final.csv"
EVT_PRELIM = ROOT / "data" / "processed" / "events_prelim.csv"
FIG_OUT = ROOT / "results" / "figures" / "caar_primary.png"
TBL_OUT = ROOT / "results" / "tables" / "caar_path.csv"
LO, HI, WIN = -10, 60, (2, 20)
N_BOOT = 10_000


def load_panel() -> pd.DataFrame:
    frames = []
    for p in sorted(PRICES_DIR.glob("chunk_*.parquet")):
        try:
            frames.append(pd.read_parquet(p))
        except Exception:
            continue
    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot(index="date", columns="symbol", values="close")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def load_mkt() -> pd.Series:
    idx = pd.read_csv(INDEX)
    sm = idx[idx["index_name"] == "Nifty Smallcap 250"].copy()
    sm["index_date"] = pd.to_datetime(sm["index_date"])
    sm = sm.set_index("index_date")["close"].sort_index().dropna()
    return np.log(sm).diff().dropna()


def caar_path(ar_matrix: pd.DataFrame) -> pd.DataFrame:
    sub = ar_matrix.loc[:, LO:HI]
    cum = sub.cumsum(axis=1)
    caar = cum.mean(axis=0)
    rng = np.random.default_rng(7)
    rows = cum.values
    n = rows.shape[0]
    idx = rng.integers(0, n, size=(N_BOOT, n))
    boots = rows[idx].mean(axis=1)
    lo = pd.Series(np.percentile(boots, 2.5, axis=0), index=cum.columns)
    hi = pd.Series(np.percentile(boots, 97.5, axis=0), index=cum.columns)
    return pd.DataFrame({"caar": caar, "ci_lo": lo, "ci_hi": hi})


def main() -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    events_path = EVT_FINAL if EVT_FINAL.exists() else EVT_PRELIM
    ev = pd.read_csv(events_path)
    ev["t0"] = pd.to_datetime(ev["t0"])
    ev = ev.reset_index(drop=True)

    wide = load_panel()
    ret = A.log_returns(wide)
    mkt = load_mkt()
    ar_matrix = A.build_ar_matrix(ev, ret, mkt)
    print(f"aligned {len(ar_matrix)} events (of {len(ev)})")

    head = A.caar_with_bootstrap_ci(ar_matrix, *WIN)
    print(f"CAAR[+2,+20] = {head['caar']*100:.2f}%  "
          f"95% CI [{head['ci_lo']*100:.2f}, {head['ci_hi']*100:.2f}]  "
          f"({head['pct_positive']*100:.0f}% positive, n={head['n']})")

    path = caar_path(ar_matrix)
    TBL_OUT.parent.mkdir(parents=True, exist_ok=True)
    path.to_csv(TBL_OUT)

    FIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = path.index.values
    ax.fill_between(x, path["ci_lo"] * 100, path["ci_hi"] * 100,
                    color="#9ecae1", alpha=0.5, label="95% bootstrap CI")
    ax.plot(x, path["caar"] * 100, color="#08306b", lw=1.8, label="CAAR")
    ax.axhline(0, color="grey", lw=0.6)
    ax.axvline(0, color="black", lw=0.7)
    ax.axvspan(WIN[0], WIN[1], color="#fee0d2", alpha=0.6, label="[+2,+20]")
    ax.set_xlabel("Trading days relative to announcement ($t=0$)")
    ax.set_ylabel("Cumulative abnormal return (%)")
    ax.set_title("Market-adjusted CAAR around order-win announcements")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_OUT, dpi=150)
    print(f"-> {FIG_OUT}")


if __name__ == "__main__":
    main()
