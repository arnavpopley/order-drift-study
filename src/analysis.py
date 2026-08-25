"""Event-study analysis primitives.

Pure functions: no I/O. All take/return pandas objects so they can be unit
tested against synthetic panels (tests/test_analysis.py).

Conventions:
    - `panel`: DataFrame indexed by date with columns symbol -> close price
      (wide). Returns are log differences.
    - offsets are TRADING-DAY offsets relative to t0, aligned per event via
      each symbol's own return series position.
"""

import numpy as np
import pandas as pd


def log_returns(prices_wide: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices_wide.sort_index()).diff()


def align_event_ar(
    ret: pd.DataFrame,
    mkt_ret: pd.Series,
    symbol: str,
    t0: pd.Timestamp,
    min_obs: int = 100,
) -> dict[int, float] | None:
    """Market-adjusted ARs for one event over offsets [-130, +60].

    Offsets index the SYMBOL's own non-NaN return sequence around its last
    valid return at or before t0's close (t0 itself = offset 0).
    """
    if symbol not in ret.columns:
        return None
    s = ret[symbol].dropna()
    pos = s.index.searchsorted(t0, side="right") - 1
    if pos < 130 or pos >= len(s):
        return None
    lo, hi = pos - 130, min(pos + 60, len(s) - 1)
    sym_slice = s.iloc[lo : hi + 1]
    mkt = mkt_ret.reindex(sym_slice.index)
    ars = (sym_slice - mkt).dropna()
    if len(ars) < min_obs // 2:
        return None
    return {i - 130: v for i, v in enumerate(ars.values)}


def build_ar_matrix(events: pd.DataFrame, ret: pd.DataFrame, mkt_ret: pd.Series) -> pd.DataFrame:
    """Rows = events (indexed like `events`), cols = offsets -130..+60."""
    out = {}
    for eid, row in events.iterrows():
        ar = align_event_ar(ret, mkt_ret, row["symbol"], pd.Timestamp(row["t0"]))
        if ar is not None:
            out[eid] = ar
    if not out:
        raise ValueError("no events aligned")
    return pd.DataFrame.from_dict(out, orient="index").sort_index(axis=1)


def car(ar_row: pd.Series, start: int, end: int) -> float:
    return float(ar_row.loc[start:end].sum())


def caar_with_bootstrap_ci(
    ar_matrix: pd.DataFrame,
    start: int,
    end: int,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict[str, float]:
    cars = ar_matrix.apply(lambda r: car(r, start, end), axis=1)
    point = float(cars.mean())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(cars), size=(n_boot, len(cars)))
    boots = cars.values[idx].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"n": len(cars), "caar": point, "ci_lo": float(lo), "ci_hi": float(hi),
            "pct_positive": float((cars > 0).mean())}


def bmp_test(
    ar_matrix: pd.DataFrame,
    est_start: int = -130,
    est_end: int = -11,
    evt_start: int = 0,
    evt_end: int = 1,
) -> dict[str, float]:
    """Boehmer-Masumeci-Poulsen standardized test on the event window.

    Per-event sigma from estimation-window ARs (market-adjusted null:
    AR volatility in the estimation period). SAR_i = CAR_i / (sigma_i *
    sqrt(L_evt)). t = mean(SAR) / (sd(SAR)/sqrt(N)).
    """
    def sigmas(row: pd.Series) -> float | None:
        est = row.loc[est_start:est_end].dropna()
        if len(est) < 60:
            return None
        return float(est.std(ddof=1))

    L_evt = evt_end - evt_start + 1
    sar_list = []
    for _, row in ar_matrix.iterrows():
        s = sigmas(row)
        if s and s > 0:
            sar_list.append(car(row, evt_start, evt_end) / (s * np.sqrt(L_evt)))
    sar = np.array(sar_list)
    if len(sar) < 5:
        return {"n": len(sar), "t": np.nan}
    t = sar.mean() / (sar.std(ddof=1) / np.sqrt(len(sar)))
    return {"n": len(sar), "t": float(t)}


def calendar_time_portfolio(
    daily_ret_wide: pd.DataFrame,
    events: pd.DataFrame,
    holding: int = 20,
) -> pd.Series:
    """Equal-weight portfolio each day of all stocks with t0 within past
    `holding` trading days. Returns daily portfolio simple returns."""
    ret = np.expm1(daily_ret_wide)
    dates = ret.index
    holdings = {}
    for _, row in events.iterrows():
        sym = row["symbol"]
        if sym not in ret.columns:
            continue
        sdates = ret[sym].dropna().index
        pos = sdates.searchsorted(pd.Timestamp(row["t0"]))
        for p in range(pos, min(pos + holding, len(sdates))):
            holdings.setdefault(sdates[p], []).append(sym)
    port = {}
    for d, syms in holdings.items():
        vals = ret.loc[d, list(dict.fromkeys(syms))].dropna()
        if len(vals):
            port[d] = float(vals.mean())
    return pd.Series(port).sort_index()


def nw_alpha(
    port_ret: pd.Series,
    factors: pd.DataFrame,
    maxlags: int = 20,
) -> dict[str, float]:
    """OLS of portfolio excess returns on factors; Newey-West alpha."""
    import statsmodels.api as sm

    df = factors.join(port_ret.rename("port"), how="inner").dropna()
    X = sm.add_constant(df.drop(columns=["port"]))
    res = sm.OLS(df["port"], X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "alpha_daily": float(res.params["const"]),
        "alpha_annualized": float(res.params["const"] * 250),
        "t": float(res.tvalues["const"]),
        "n_days": int(res.nobs),
    }
