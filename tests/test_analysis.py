"""Synthetic-data tests for the analysis primitives.

A fake market is simulated where we KNOW the truth: zero-drift events must
show CAAR ~ 0 (CI covers 0); planted +1%/day drift for 20 days must be
recovered inside the bootstrap CI.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis import (
    bmp_test,
    build_ar_matrix,
    caar_with_bootstrap_ci,
    calendar_time_portfolio,
    car,
    nw_alpha,
)


def make_market(n_days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    mkt = pd.Series(rng.normal(0.0003, 0.008, n_days), index=idx)
    return pd.DataFrame({"MKT": mkt})


def add_stock(market: pd.DataFrame, symbol: str, beta: float = 1.0, drift: dict[int, float] | None = None, seed: int = 0):
    rng = np.random.default_rng(seed)
    mkt = market["MKT"]
    ret = beta * mkt + rng.normal(0, 0.01, len(mkt))
    pos = 250
    if drift:
        for off, r in drift.items():
            ret.iloc[pos + off] += r
    out = market.copy()
    out["MKT"] = 100.0 * np.exp(market["MKT"].cumsum())
    out[symbol] = 100.0 * np.exp(ret.cumsum())
    return out, pos


@pytest.fixture(scope="module")
def setup():
    market = make_market()
    return market


def _events_for(symbols_with_t0):
    return pd.DataFrame(
        [{"symbol": s, "t0": t} for s, t in symbols_with_t0]
    ).set_index(pd.RangeIndex(len(symbols_with_t0)))


def test_zero_drift_caar_covers_zero(setup):
    market = setup
    frames, evs = [], []
    for i in range(40):
        f, pos = add_stock(market, f"S{i}", seed=i)
        frames.append(f)
        evs.append((f"S{i}", f.index[pos]))
    merged = pd.concat(frames).groupby(level=0).last()
    from src.analysis import log_returns
    ret = log_returns(merged)
    events = _events_for(evs)
    arm = build_ar_matrix(events, ret, ret["MKT"])
    res = caar_with_bootstrap_ci(arm, 2, 20, n_boot=2000)
    assert res["ci_lo"] < 0 < res["ci_hi"]
    assert abs(res["caar"]) < 0.03


def test_planted_drift_is_recovered(setup):
    market = setup
    frames, evs = [], []
    for i in range(40):
        f, pos = add_stock(market, f"D{i}", drift={o: 0.01 for o in range(2, 22)}, seed=100 + i)
        frames.append(f)
        evs.append((f"D{i}", f.index[pos]))
    merged = pd.concat(frames).groupby(level=0).last()
    from src.analysis import log_returns
    ret = log_returns(merged)
    events = _events_for(evs)
    arm = build_ar_matrix(events, ret, ret["MKT"])
    res = caar_with_bootstrap_ci(arm, 2, 21, n_boot=2000)
    assert res["caar"] > 0.15
    assert res["ci_lo"] > 0


def test_car_sums_offsets():
    row = pd.Series({-1: 0.01, 0: 0.02, 1: 0.03, 2: -0.01})
    assert abs(car(row, 0, 1) - 0.05) < 1e-12


def test_bmp_rejects_strong_effect_and_not_noise(setup):
    market = setup
    def arm_for(prefix, drift):
        frames, evs = [], []
        for i in range(30):
            f, pos = add_stock(market, f"{prefix}{i}", drift=drift, seed=hash(prefix + str(i)) % 10000)
            frames.append(f)
            evs.append((f"{prefix}{i}", f.index[pos]))
        merged = pd.concat(frames).groupby(level=0).last()
        from src.analysis import log_returns
        ret = log_returns(merged)
        return build_ar_matrix(_events_for(evs), ret, ret["MKT"])

    noise = bmp_test(arm_for("N", None))
    strong = bmp_test(arm_for("B", {0: 0.05, 1: 0.05}))
    assert abs(noise["t"]) < 3
    assert strong["t"] > 5


def test_calendar_time_portfolio_equal_weights(setup):
    dates = setup.index
    two_stocks = pd.DataFrame(
        {"A": np.log1p(0.001), "B": np.log1p(0.003)}, index=dates)
    events = pd.DataFrame([{"symbol": "A", "t0": dates[10]},
                           {"symbol": "B", "t0": dates[11]}])
    port = calendar_time_portfolio(two_stocks, events, holding=2)
    assert len(port) == 3
    assert port.loc[dates[11]] == pytest.approx(0.002, abs=1e-9)
    assert port.loc[dates[10]] == pytest.approx(0.001, abs=1e-9)


def test_nw_alpha_recovers_no_alpha():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-01-01", periods=500)
    factors = pd.DataFrame({
        "MKT_RF": rng.normal(0.0004, 0.008, 500),
        "SMB": rng.normal(0, 0.005, 500),
    }, index=idx)
    port = factors["MKT_RF"] * 1.2 + rng.normal(0, 0.004, 500)
    res = nw_alpha(port, factors)
    assert res["n_days"] == 500
    assert abs(res["alpha_daily"]) < 0.003
