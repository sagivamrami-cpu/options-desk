"""Black-Scholes-Merton pricing, greeks and implied-vol inversion.

Everything here is vectorised over numpy arrays so a full option chain can be
priced in one call. Conventions used throughout the package:

    S     spot price of the underlying
    K     strike
    T     time to expiry in YEARS (calendar, not trading days)
    r     continuously-compounded risk-free rate (0.04 == 4%)
    q     continuous dividend / carry yield
    sigma implied volatility as a decimal (0.20 == 20%)
    right 'C' or 'P'

Greeks are returned in their raw mathematical units (per 1.0 change in the
input). The reporting layer is responsible for rescaling them into the units
traders actually quote -- vega per 1 vol POINT, theta per DAY, and so on.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

__all__ = [
    "d1_d2", "price", "delta", "gamma", "vega", "theta",
    "vanna", "charm", "vomma", "implied_vol", "implied_vol_chain",
]

_SQRT_2PI = np.sqrt(2.0 * np.pi)
# Below this much time or vol the closed form degenerates; we clamp instead of
# emitting inf/nan so a single stale 0DTE quote cannot poison a whole chain.
_MIN_T = 1e-6
_MIN_SIGMA = 1e-6


def _pdf(x):
    return np.exp(-0.5 * np.asarray(x, dtype=float) ** 2) / _SQRT_2PI


def _prep(S, K, T, r, q, sigma):
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.maximum(np.asarray(T, dtype=float), _MIN_T)
    r = np.asarray(r, dtype=float)
    q = np.asarray(q, dtype=float)
    sigma = np.maximum(np.asarray(sigma, dtype=float), _MIN_SIGMA)
    return S, K, T, r, q, sigma


def _is_call(right):
    """Accept 'C'/'call'/'CALL'/True and anything else means put."""
    arr = np.asarray(right)
    if arr.dtype == bool:
        return arr
    return np.char.upper(arr.astype(str).astype("U4")) == np.array("C", dtype="U4")


def d1_d2(S, K, T, r=0.0, q=0.0, sigma=0.2):
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    vol_t = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / vol_t
    return d1, d1 - vol_t


def price(S, K, T, r=0.0, q=0.0, sigma=0.2, right="C"):
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    disc_r, disc_q = np.exp(-r * T), np.exp(-q * T)
    call = S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    put = K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)
    return np.where(_is_call(right), call, put)


# --------------------------------------------------------------------------
# First-order greeks
# --------------------------------------------------------------------------

def delta(S, K, T, r=0.0, q=0.0, sigma=0.2, right="C"):
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    disc_q = np.exp(-q * T)
    return np.where(_is_call(right), disc_q * norm.cdf(d1), -disc_q * norm.cdf(-d1))


def gamma(S, K, T, r=0.0, q=0.0, sigma=0.2):
    """Identical for calls and puts -- this is the workhorse behind GEX."""
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    return np.exp(-q * T) * _pdf(d1) / (S * sigma * np.sqrt(T))


def vega(S, K, T, r=0.0, q=0.0, sigma=0.2):
    """Per 1.0 change in vol. Divide by 100 for the per-vol-point convention."""
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    return S * np.exp(-q * T) * _pdf(d1) * np.sqrt(T)


def theta(S, K, T, r=0.0, q=0.0, sigma=0.2, right="C"):
    """Per YEAR. Divide by 365 for the per-calendar-day convention."""
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    disc_r, disc_q = np.exp(-r * T), np.exp(-q * T)
    decay = -S * disc_q * _pdf(d1) * sigma / (2.0 * np.sqrt(T))
    call = decay - r * K * disc_r * norm.cdf(d2) + q * S * disc_q * norm.cdf(d1)
    put = decay + r * K * disc_r * norm.cdf(-d2) - q * S * disc_q * norm.cdf(-d1)
    return np.where(_is_call(right), call, put)


# --------------------------------------------------------------------------
# Second-order greeks -- the ones that drive dealer flows between expiries
# --------------------------------------------------------------------------

def vanna(S, K, T, r=0.0, q=0.0, sigma=0.2):
    """d(delta)/d(vol), equivalently d(vega)/d(spot). Same for calls and puts.

    Sign matters more than magnitude here: when vol falls, vanna tells you which
    way dealers must rebalance their delta hedge even if spot never moved.
    """
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    return -np.exp(-q * T) * _pdf(d1) * d2 / sigma


def charm(S, K, T, r=0.0, q=0.0, sigma=0.2, right="C"):
    """d(delta)/d(time), per YEAR. Also called delta bleed or delta decay.

    This is why a quiet Friday drifts: as T shrinks, deltas migrate toward 0 or
    1 and dealers must mechanically buy or sell the underlying to stay flat.
    """
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    disc_q = np.exp(-q * T)
    vol_t = sigma * np.sqrt(T)
    common = -disc_q * _pdf(d1) * (2.0 * (r - q) * T - d2 * vol_t) / (2.0 * T * vol_t)
    call = q * disc_q * norm.cdf(d1) + common
    put = -q * disc_q * norm.cdf(-d1) + common
    return np.where(_is_call(right), call, put)


def vomma(S, K, T, r=0.0, q=0.0, sigma=0.2):
    """d(vega)/d(vol). Large vomma means the vega hedge itself is unstable."""
    S, K, T, r, q, sigma = _prep(S, K, T, r, q, sigma)
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    return vega(S, K, T, r, q, sigma) * d1 * d2 / sigma


# --------------------------------------------------------------------------
# Implied volatility
# --------------------------------------------------------------------------

def implied_vol(target, S, K, T, r=0.0, q=0.0, right="C",
                lo=1e-4, hi=5.0):
    """Invert a single option price for vol. Returns nan when no root exists.

    Brent is used rather than Newton because deep-OTM options have a vega close
    to zero, where Newton diverges. A no-arbitrage check runs first: if the
    quote sits outside the intrinsic-to-spot band there is no valid vol.
    """
    if not np.isfinite(target) or target <= 0 or T <= 0:
        return float("nan")

    is_call = str(right).upper().startswith("C")
    disc_r, disc_q = np.exp(-r * T), np.exp(-q * T)
    if is_call:
        floor_, cap = max(0.0, S * disc_q - K * disc_r), S * disc_q
    else:
        floor_, cap = max(0.0, K * disc_r - S * disc_q), K * disc_r
    if target < floor_ - 1e-8 or target > cap + 1e-8:
        return float("nan")

    def obj(sig):
        return float(price(S, K, T, r, q, sig, right)) - target

    try:
        if obj(lo) * obj(hi) > 0:
            return float("nan")
        return float(brentq(obj, lo, hi, xtol=1e-6, maxiter=100))
    except (ValueError, RuntimeError):
        return float("nan")


def implied_vol_chain(targets, S, K, T, r=0.0, q=0.0, right="C"):
    """Vectorised wrapper: one implied_vol call per row, nan-safe."""
    targets = np.atleast_1d(np.asarray(targets, dtype=float))
    K = np.broadcast_to(np.atleast_1d(K), targets.shape)
    T = np.broadcast_to(np.atleast_1d(T), targets.shape)
    right = np.broadcast_to(np.atleast_1d(np.asarray(right)), targets.shape)
    return np.array([
        implied_vol(t, S, k, tt, r, q, rr)
        for t, k, tt, rr in zip(targets, K, T, right)
    ])
