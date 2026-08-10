"""The identities that must hold, or the numbers downstream are fiction.

Each test here corresponds to a bug that actually shipped and was caught by
checking the identity by hand. They exist so the next change cannot break one
of them quietly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optionsdesk import blackscholes as bs
from optionsdesk import metrics as M
from optionsdesk import structures as X
from optionsdesk import surface as S

from .conftest import RATE, SPOT, TRUE_CARRY


# ======================================================================
# Black-Scholes
# ======================================================================

def test_put_call_parity():
    S_, K, T, r, q, sig = 500.0, 505.0, 0.25, 0.04, 0.01, 0.22
    c = float(bs.price(S_, K, T, r, q, sig, "C"))
    p = float(bs.price(S_, K, T, r, q, sig, "P"))
    assert c - p == pytest.approx(S_ * np.exp(-q * T) - K * np.exp(-r * T), abs=1e-9)


@pytest.mark.parametrize("right", ["C", "P"])
def test_greeks_match_numerical_derivatives(right):
    S_, K, T, r, q, sig = 500.0, 500.0, 0.5, 0.04, 0.01, 0.25
    h = 1e-5
    px = lambda s=S_, t=T, v=sig: float(bs.price(s, K, t, r, q, v, right))

    assert float(bs.delta(S_, K, T, r, q, sig, right)) == pytest.approx(
        (px(s=S_ + h) - px(s=S_ - h)) / (2 * h), rel=1e-5)
    assert float(bs.vega(S_, K, T, r, q, sig)) == pytest.approx(
        (px(v=sig + h) - px(v=sig - h)) / (2 * h), rel=1e-5)

    dlt = lambda s=S_, t=T, v=sig: float(bs.delta(s, K, t, r, q, v, right))
    assert float(bs.vanna(S_, K, T, r, q, sig)) == pytest.approx(
        (dlt(v=sig + h) - dlt(v=sig - h)) / (2 * h), rel=1e-4)
    assert float(bs.charm(S_, K, T, r, q, sig, right)) == pytest.approx(
        -(dlt(t=T + h) - dlt(t=T - h)) / (2 * h), rel=1e-4)


def test_implied_vol_round_trip():
    for sig in (0.08, 0.20, 0.65, 1.40):
        px = float(bs.price(500.0, 520.0, 0.3, 0.04, 0.01, sig, "C"))
        assert bs.implied_vol(px, 500.0, 520.0, 0.3, 0.04, 0.01, "C") == pytest.approx(sig, abs=1e-5)


def test_implied_vol_returns_nan_outside_arbitrage_bounds():
    # A price above the spot cannot be a call; there is no vol that produces it.
    assert np.isnan(bs.implied_vol(600.0, 500.0, 500.0, 0.3, 0.04, 0.0, "C"))


# ======================================================================
# Forward and surface
# ======================================================================

def test_implied_forward_recovers_the_true_carry(snapshot):
    """Regression: assuming q=0 put OTM puts 27-64 cents under the market."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    for exp, grp in df.groupby("expiry"):
        T = float(grp["T"].iloc[0])
        F, carry = S.implied_forward(grp, SPOT, T, RATE)
        assert F == pytest.approx(SPOT * np.exp((RATE - TRUE_CARRY) * T), rel=1e-4)
        assert carry == pytest.approx(TRUE_CARRY, abs=5e-4)


def test_svi_fit_recovers_the_true_surface(snapshot):
    df = M.prepare(snapshot, r=RATE, q=0.0)
    fits = S.fit_all_expiries(df, SPOT, r=RATE)
    assert len(fits) == 3, f"expected 3 fitted expiries, got {fits.explain()}"
    for exp, f in fits.items():
        # Sub-basis-point fit against a surface we generated ourselves.
        assert f["params"].rmse < 0.001, f"{exp}: rmse {f['params'].rmse}"
        assert f["params"].is_arbitrage_free()[0]


def test_bad_fits_are_rejected_not_returned(snapshot):
    """A wandering smile manufactures fake mispricings at every strike, so a
    fit that cannot meet the tolerance must be dropped rather than returned."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    fits = S.fit_all_expiries(df, SPOT, r=RATE, max_rmse=1e-9)
    assert len(fits) == 0
    assert len(fits.rejected) == 3
    assert all("RMSE" in why for why in fits.rejected.values())


# ======================================================================
# Risk-neutral density
# ======================================================================

def test_density_integrates_to_one_and_means_the_forward(snapshot):
    """Breeden-Litzenberger sanity. If E[S_T] drifts off the forward, every
    expected value computed against this density is biased."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    fits = S.fit_all_expiries(df, SPOT, r=RATE)
    for exp, f in fits.items():
        d = S.risk_neutral_density(f["params"], f["F"], f["T"], r=RATE)
        K, dens = d["strike"].to_numpy(), d["density"].to_numpy()
        dK = np.gradient(K)
        assert float((dens * dK).sum()) == pytest.approx(1.0, abs=1e-3)
        # Raw mass shows truncation before normalisation hides it.
        assert d.attrs["raw_mass"] == pytest.approx(1.0, abs=5e-3)
        # The martingale condition: E[S_T] == F. Within 5 bp.
        assert abs(d.attrs["martingale_error"]) < 5e-4
        assert float((K * dens * dK).sum()) == pytest.approx(f["F"], rel=1e-3)


def test_density_reprices_vanilla_options(snapshot):
    """Integrating the payoff against the density must return the option price."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    fits = S.fit_all_expiries(df, SPOT, r=RATE)
    exp = sorted(fits, key=lambda e: fits[e]["T"])[-1]
    f = fits[exp]
    d = S.risk_neutral_density(f["params"], f["F"], f["T"], r=RATE)
    K, dens = d["strike"].to_numpy(), d["density"].to_numpy()
    dK = np.gradient(K)
    disc = np.exp(-RATE * f["T"])

    for strike in (SPOT * 0.95, SPOT, SPOT * 1.05):
        for right in ("C", "P"):
            payoff = (np.maximum(K - strike, 0.0) if right == "C"
                      else np.maximum(strike - K, 0.0))
            integrated = float((payoff * dens * dK).sum()) * disc
            iv = float(f["params"].iv(np.log(strike / f["F"]), f["T"]))
            model = float(bs.price(SPOT, strike, f["T"], RATE, TRUE_CARRY, iv, right))
            assert integrated == pytest.approx(model, abs=0.05)


# ======================================================================
# THE identity: risk-neutral EV is zero minus costs
# ======================================================================

def test_risk_neutral_ev_at_mid_is_zero(snapshot):
    """The single most important test in the suite.

    Under the risk-neutral density the expected profit of ANY structure is zero
    before costs. Every "high expected value" screen that does not respect this
    is measuring its own numerical error. Three separate bugs -- undiscounted
    payoffs, a truncated integration grid, and an assumed forward -- were each
    caught by this identity failing.
    """
    df = M.prepare(snapshot, r=RATE, q=0.0)
    fits = S.fit_all_expiries(df, SPOT, r=RATE)
    exp = sorted(fits, key=lambda e: fits[e]["T"])[-1]
    f = fits[exp]

    d = S.risk_neutral_density(f["params"], f["F"], f["T"], r=RATE)
    grid, dens = d["strike"].to_numpy(), d["density"].to_numpy()

    candidates = (
        X.generate_verticals(df, exp, SPOT, "P", (0.16,), (2, 5))
        + X.generate_verticals(df, exp, SPOT, "C", (0.16,), (2, 5))
        + X.generate_butterflies(df, exp, SPOT, (2, 5))
        + X.generate_condors(df, exp, SPOT, (0.16,), (3,))
        + X.generate_strangles(df, exp, SPOT, (0.16,))
    )
    assert candidates, "generators produced nothing to test"

    for st in candidates:
        res = X.evaluate(df, st, SPOT, grid, dens, fits, exp, r=RATE,
                         use_executable=False)      # mid prices: zero cost
        assert "error" not in res
        scale = max(abs(res["max_loss"]), abs(res["max_profit"]), 1.0)
        assert abs(res["ev"]) / scale < 0.02, (
            f"{st.name}: risk-neutral EV {res['ev']:.2f} is "
            f"{res['ev']/scale:.1%} of the payoff range -- identity violated"
        )


def test_executable_pricing_costs_the_spread(snapshot):
    """Longs must lift the ask and shorts must hit the bid, always."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    exp = sorted(df["expiry"].unique())[-1]
    for st in X.generate_verticals(df, exp, SPOT, "P", (0.16,), (2,)):
        px = X.price_structure(df, st)
        assert px["tradeable"]
        # Two legs, $0.02 half-spread each, 100 multiplier => $4 round of slippage.
        assert px["slippage"] == pytest.approx(4.0, abs=1e-6)
        assert px["executable_cost"] > px["mid_cost"]


# ======================================================================
# Empirical density and drift
# ======================================================================

def test_recentering_removes_sample_drift(snapshot):
    """Regression: with a trending lookback, every bullish structure scored a
    large fake edge. On live QQQ the unrecentred scan returned bull put spreads
    as all ten top candidates."""
    grid = np.linspace(SPOT * 0.5, SPOT * 1.6, 4001)
    F = SPOT * np.exp((RATE - TRUE_CARRY) * (45 / 365))

    raw = X.empirical_density(snapshot.history, SPOT, 45, grid, recenter_to=None)
    fixed = X.empirical_density(snapshot.history, SPOT, 45, grid, recenter_to=F)
    assert raw.size and fixed.size

    mean = lambda d: float((grid * d * np.gradient(grid)).sum() /
                           (d * np.gradient(grid)).sum())

    # Recentring must land the mean exactly on the forward.
    assert mean(fixed) == pytest.approx(F, rel=2e-3)

    # And the raw sample must be materially off it. The DIRECTION is
    # deliberately not asserted: a random path can drift either way, and the
    # property being tested is that whatever drift the sample happened to
    # contain gets removed -- not that it was positive. Asserting the sign
    # would make this test pass or fail on the seed.
    assert abs(mean(raw) - F) > 0.01 * F, (
        f"sample drift too small to test: raw {mean(raw):.2f} vs F {F:.2f}"
    )


def test_empirical_density_preserves_volatility(snapshot):
    """Recentring must move the distribution, not reshape it."""
    grid = np.linspace(SPOT * 0.5, SPOT * 1.6, 4001)
    F = SPOT * np.exp((RATE - TRUE_CARRY) * (45 / 365))
    d = X.empirical_density(snapshot.history, SPOT, 45, grid, recenter_to=F)
    w = d * np.gradient(grid)
    w = w / w.sum()
    mean = float((grid * w).sum())
    sd = float(np.sqrt(((grid - mean) ** 2 * w).sum()))
    # 18% annual vol over 45 calendar days ~ 6.5% of spot, plus KDE smoothing.
    assert 0.04 < sd / SPOT < 0.10


# ======================================================================
# Structures
# ======================================================================

def test_vertical_spread_payoff_bounds(snapshot):
    """Max profit and max loss of a credit spread are analytic; check them."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    exp = sorted(df["expiry"].unique())[-1]
    st = X.generate_verticals(df, exp, SPOT, "P", (0.16,), (5,))[0]
    short_k = max(l.strike for l in st.legs)
    long_k = min(l.strike for l in st.legs)
    width = (short_k - long_k) * 100

    grid = np.linspace(SPOT * 0.5, SPOT * 1.6, 4001)
    dens = np.ones_like(grid)
    res = X.evaluate(df, st, SPOT, grid, dens, {}, exp, r=RATE, use_executable=False)
    credit = -res["cost"]

    # evaluate() discounts the expiry payoff to present value, so both bounds
    # carry the discount factor. Comparing an undiscounted bound against a
    # present-value result is exactly the mix-up this suite exists to prevent.
    T = float(df[df["expiry"] == exp]["T"].iloc[0])
    disc = np.exp(-RATE * T)
    assert res["max_profit"] == pytest.approx(credit * disc, abs=1.0)
    assert res["max_loss"] == pytest.approx(-(width * disc - credit * disc), abs=1.5)


def test_undefined_risk_is_excluded_from_ranking(snapshot):
    """Max loss on a naked short is an artefact of where the grid stops, so it
    must never be ranked against structures with a real cap."""
    df = M.prepare(snapshot, r=RATE, q=0.0)
    exp = sorted(df["expiry"].unique())[-1]
    reports = [{"name": "capped", "tradeable": True, "widest_rel_spread": 0.05,
                "max_loss": -100.0, "edge": 10.0, "pop_empirical": 0.7},
               {"name": "naked", "tradeable": True, "widest_rel_spread": 0.05,
                "max_loss": float("-inf"), "edge": 99.0, "pop_empirical": 0.9}]
    ranked = X.rank(reports, require_defined_risk=True)
    assert list(ranked["name"]) == ["capped"]


# ======================================================================
# Alerting
# ======================================================================

def _fake_scan(spot=500.0, flip=490.0, vrp=-0.05, regime="long_gamma",
               n_positive=0, best_ev=0.0):
    import pandas as pd
    cands = pd.DataFrame([{
        "name": "bull put 480/475", "expiry": "2026-09-18", "cost": -50.0,
        "ev_empirical": best_ev, "edge": 12.0, "pop_empirical": 0.8,
        "max_loss": -450.0, "slippage": 4.0,
    }] * max(n_positive, 0))
    return {
        "symbol": "TEST", "spot": spot, "candidates": cands, "rejected": {},
        "regime": {"gamma_regime": regime, "flip_level": flip,
                   "spot_vs_flip_pct": (spot - flip) / spot * 100,
                   "net_gex": 1e9, "iv30": 0.20, "rv20": 0.25, "vrp": vrp},
    }


def test_alert_fires_on_flip_crossing_not_on_level():
    from optionsdesk import alerts as AL
    prev = {"spot_vs_flip_pct": 2.0, "regime": "long_gamma", "vrp": -0.05,
            "n_positive_ev": 0, "best_ev": ""}
    # Still above the flip: no crossing alert.
    quiet = AL.evaluate(_fake_scan(spot=505.0, flip=490.0), prev)
    assert not [a for a in quiet if a.kind == "gamma_flip_crossed"]

    # Now below it: exactly one crossing alert, and it must be critical.
    crossed = AL.evaluate(_fake_scan(spot=485.0, flip=490.0), prev)
    hits = [a for a in crossed if a.kind == "gamma_flip_crossed"]
    assert len(hits) == 1 and hits[0].severity == "critical"
    assert "AMPLIFIES" in hits[0].detail["implication"]


def test_opportunity_alert_does_not_repeat():
    """Regression: an earlier version re-sent an identical alert every pass for
    as long as the condition held, which is how an alert channel becomes noise."""
    from optionsdesk import alerts as AL
    scan = _fake_scan(n_positive=2, best_ev=25.0)

    first = AL.evaluate(scan, None)
    assert [a for a in first if a.kind == "positive_expectancy"]

    prev = {"spot_vs_flip_pct": 2.0, "regime": "long_gamma", "vrp": -0.05,
            "n_positive_ev": 2, "best_ev": 25.0}
    again = AL.evaluate(scan, prev)
    assert not [a for a in again if a.kind == "positive_expectancy"]

    # A materially better opportunity does get through.
    better = AL.evaluate(_fake_scan(n_positive=2, best_ev=60.0), prev)
    assert [a for a in better if a.kind == "positive_expectancy"]


def test_vrp_sign_change_alerts_once():
    from optionsdesk import alerts as AL
    prev = {"spot_vs_flip_pct": 2.0, "regime": "long_gamma", "vrp": 0.03,
            "n_positive_ev": 0, "best_ev": ""}
    flipped = AL.evaluate(_fake_scan(vrp=-0.02), prev)
    hits = [a for a in flipped if a.kind == "vrp_sign_change"]
    assert len(hits) == 1 and "NEGATIVE" in hits[0].message

    prev2 = dict(prev, vrp=-0.02)
    assert not [a for a in AL.evaluate(_fake_scan(vrp=-0.02), prev2)
                if a.kind == "vrp_sign_change"]


# ======================================================================
# Data quality
# ======================================================================

def test_empty_open_interest_marks_the_report_degraded():
    """Regression, and the costliest bug in this project's history.

    Pre-market the provider returned bid=ask=0 and open_interest=0 for every
    contract. GEX was computed over zero open interest, came back zero, the
    flip level and max pain came back nan, and the report was delivered to
    Telegram with no warning at all. Nothing in the stack noticed the inputs
    were empty.
    """
    import datetime as _dt
    from optionsdesk.sources.base import ChainSnapshot
    from .conftest import build_chain, build_history

    chain = build_chain()
    chain["open_interest"] = 0.0
    chain["bid"] = 0.0
    chain["ask"] = 0.0

    snap = ChainSnapshot("TEST", SPOT, chain, _dt.datetime.now(), "synthetic",
                         build_history())
    q = snap.quality()
    assert q["usable_for_positioning"] is False
    assert q["usable_for_surface"] is False
    assert any("open interest is zero" in p for p in q["problems"])


def test_healthy_chain_is_not_flagged(snapshot):
    q = snapshot.quality()
    assert q["usable_for_positioning"] is True
    assert q["usable_for_surface"] is True
    assert q["problems"] == []


def test_degraded_report_is_not_rendered_as_a_normal_digest():
    """The formatter must refuse, in both languages, rather than print zeros."""
    from optionsdesk import notify
    dead = [{"symbol": "QQQ", "asof": "2026-08-10T08:30:00", "degraded": True,
             "data_quality": {"problems": ["open interest is zero across the whole chain"]},
             "gex": {}, "vol": {}, "read": {}, "expiries": []}]

    he = notify.format_report_he(dead)
    assert "אין דוח היום" in he
    assert "GEX" not in he.replace("open interest is zero", "")

    en = notify.format_report(dead)
    assert "No report today" in en
