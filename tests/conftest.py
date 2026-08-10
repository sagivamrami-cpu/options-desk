"""A synthetic option market with a KNOWN answer.

Every test in this suite runs against a chain generated from a specified SVI
surface and a specified forward, priced exactly by Black-Scholes. Because the
truth is known by construction, a failure points at the code rather than at a
market that moved.

This matters more than test hygiene. Five real bugs were caught during
development purely by checking mathematical identities against live data --
present-versus-future value, tail truncation, an assumed forward, sample drift,
and edge confused with expectancy. Live data cannot be a regression test: it
changes hourly and it never tells you what the right answer was. A synthetic
market can.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from optionsdesk import blackscholes as bs
from optionsdesk.sources.base import ChainSnapshot

# Known-truth parameters. Deliberately equity-like: negative skew, ~20% ATM vol.
TRUE_SVI = dict(a=0.008, b=0.10, rho=-0.65, m=0.02, sigma=0.12)
TRUE_CARRY = 0.010          # 1% dividend / carry yield
RATE = 0.04
SPOT = 500.0
HALF_SPREAD = 0.02          # $0.02 each side, so mid is the exact model price


def _svi_total_variance(k, a, b, rho, m, sigma):
    """Raw SVI total variance at a FIXED per-year level (a, b are per-year).

    build_chain multiplies this by T per slice -- see the note there. Without
    that scaling, every expiry gets the SAME total variance regardless of
    maturity, and iv = sqrt(w/T) explodes at short T. That is not a hypothetical:
    the first version of this fixture generated a 7-day ATM call priced at
    105.7% implied vol purely from this, which silently made a calendar spread
    look like a $92 debit against a $2,231 expected value. The fitting code
    was never wrong -- it correctly recovered whatever surface the fixture
    handed it. The fixture was generating a surface no real market has.
    """
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))


def build_chain(spot=SPOT, dtes=(7, 21, 45), r=RATE, q=TRUE_CARRY,
                strike_step=1.0, width=0.25, half_spread=HALF_SPREAD):
    """Generate an arbitrage-free chain whose mid prices are exactly BS prices."""
    today = pd.Timestamp.now().normalize()
    rows = []
    for dte in dtes:
        T = dte / 365.0
        F = spot * np.exp((r - q) * T)
        lo, hi = spot * (1 - width), spot * (1 + width)
        strikes = np.arange(round(lo), round(hi) + strike_step, strike_step)
        k = np.log(strikes / F)
        # Scale by T: SVI is a per-slice (single-maturity) parametrization: a
        # real surface is a family of independently shaped slices, each with
        # its OWN total variance level, not one curve reused unscaled across
        # every expiry. Multiplying by T here gives a roughly flat ATM vol
        # term structure -- a plain, realistic default -- instead of total
        # variance that does not grow with time at all.
        w = T * _svi_total_variance(k, **TRUE_SVI)
        iv = np.sqrt(np.maximum(w, 1e-8) / T)

        for right in ("C", "P"):
            px = bs.price(spot, strikes, T, r, q, iv, right)
            rows.append(pd.DataFrame({
                "expiry": today + pd.Timedelta(days=int(dte)),
                "right": right,
                "strike": strikes,
                "bid": np.maximum(px - half_spread, 0.01),
                "ask": px + half_spread,
                "mid": px,
                "last": px,
                "volume": 100.0,
                "open_interest": 500.0,
                "iv": np.nan,          # force the pipeline to solve it
                "dte": float(dte),
                "T": T,
            }))
    return pd.concat(rows, ignore_index=True)


def build_history(spot=SPOT, days=520, annual_vol=0.18, drift=0.10, seed=7):
    """Daily closes with a KNOWN volatility and a deliberately large drift.

    The drift is there on purpose: it is what the recentering test has to
    remove. A lookback carrying a 10% annual trend makes every bullish
    structure look profitable if that drift is not stripped out.
    """
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    shocks = rng.normal((drift - 0.5 * annual_vol ** 2) * dt,
                        annual_vol * np.sqrt(dt), days)
    closes = spot * np.exp(np.cumsum(shocks))
    closes = closes * (spot / closes[-1])          # end exactly at spot
    idx = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=days)
    return pd.DataFrame({"close": closes}, index=idx)


@pytest.fixture(scope="session")
def chain():
    return build_chain()


@pytest.fixture(scope="session")
def history():
    return build_history()


@pytest.fixture(scope="session")
def snapshot(chain, history):
    return ChainSnapshot(
        symbol="TEST", spot=SPOT, chain=chain,
        asof=_dt.datetime.now(), source="synthetic", history=history,
    )
