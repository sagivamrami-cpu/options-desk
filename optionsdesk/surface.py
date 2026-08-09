"""Volatility surface fitting, static-arbitrage detection and relative value.

This is the layer that answers "which specific option is mispriced", as opposed
to metrics.py which answers "how is the market positioned". It works entirely in
the cross-section: one expiry at a time, IV as a function of strike.

The method is standard sell-side practice:

  1. Convert every quote to TOTAL VARIANCE w(k) = iv^2 * T against log-moneyness
     k = ln(K/F). This is the coordinate system where the surface is smooth and
     where the no-arbitrage conditions are simple.
  2. Fit Gatheral's raw SVI to each expiry. Five parameters, and it is the
     industry default because it can reproduce an equity smile almost exactly
     while staying arbitrage-free under checkable conditions.
  3. Measure each quote's residual against the fit. That residual -- in vol
     points -- is the honest definition of "rich" or "cheap": expensive relative
     to the smile its own neighbours imply, not relative to a hunch.
  4. Check static arbitrage explicitly (butterfly and calendar).
  5. Recover the risk-neutral density by Breeden-Litzenberger, which converts
     the surface into the market's actual probability distribution.

READ THIS BEFORE TRADING ANYTHING THIS MODULE FLAGS
---------------------------------------------------
A large residual is a hypothesis, not an edge. In liquid ETF options the
overwhelming majority of apparent mispricings are one of:

  * the bid-ask spread -- you are comparing a mid that nobody will trade at
  * a stale quote on an illiquid strike, especially far wings and odd expiries
  * discrete dividends or borrow cost not in the forward you assumed
  * early-exercise value, since ETF options are American and this model is not
  * pin risk and hard-to-hedge gamma near expiry

`edge_after_costs()` exists precisely to keep this honest: it re-prices every
candidate at the side of the market you would actually have to cross. Most
flagged strikes do not survive it. That is the correct outcome, not a bug.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from . import blackscholes as bs

__all__ = [
    "SVIParams", "SurfaceFits", "fit_svi", "fit_all_expiries", "otm_smile", "smile_residuals",
    "butterfly_arbitrage", "calendar_arbitrage", "risk_neutral_density",
    "density_stats", "edge_after_costs",
]

# A residual below this is inside the noise of any real quote; do not report it.
MIN_INTERESTING_RESIDUAL = 0.01      # 1 vol point
# Quotes wider than this relative to mid are not real markets.
MAX_RELATIVE_SPREAD = 0.35


# ======================================================================
# SVI
# ======================================================================

class SVIParams:
    """Gatheral raw SVI:  w(k) = a + b * (rho*(k-m) + sqrt((k-m)^2 + sigma^2))

    w is TOTAL variance (iv^2 * T), k is log-moneyness ln(K/F).

    a      vertical level of the smile
    b      overall slope / wing steepness (b >= 0)
    rho    slope asymmetry, i.e. skew (-1 < rho < 1; equities sit near -0.7)
    m      horizontal shift of the minimum
    sigma  curvature at the minimum (sigma > 0)
    """

    __slots__ = ("a", "b", "rho", "m", "sigma", "rmse", "n_quotes")

    def __init__(self, a, b, rho, m, sigma, rmse=float("nan"), n_quotes=0):
        self.a, self.b, self.rho, self.m, self.sigma = a, b, rho, m, sigma
        self.rmse, self.n_quotes = rmse, n_quotes

    def total_variance(self, k):
        k = np.asarray(k, dtype=float)
        return self.a + self.b * (
            self.rho * (k - self.m) + np.sqrt((k - self.m) ** 2 + self.sigma ** 2)
        )

    def iv(self, k, T):
        w = np.maximum(self.total_variance(k), 1e-12)
        return np.sqrt(w / max(T, 1e-9))

    def is_arbitrage_free(self) -> tuple[bool, list[str]]:
        """Necessary conditions for a single SVI slice to admit no butterfly
        arbitrage (Gatheral & Jacquier). Not sufficient, but they catch the
        pathological fits that produce negative densities."""
        bad = []
        if self.b < 0:
            bad.append("b < 0 (wings slope the wrong way)")
        if abs(self.rho) >= 1:
            bad.append("|rho| >= 1 (degenerate skew)")
        if self.sigma <= 0:
            bad.append("sigma <= 0 (no curvature)")
        if self.a + self.b * self.sigma * np.sqrt(max(0.0, 1 - self.rho ** 2)) < 0:
            bad.append("minimum total variance is negative")
        # Lee's moment formula: wing slopes must not exceed 2.
        if self.b * (1 + abs(self.rho)) > 2.0:
            bad.append("wing slope > 2 (violates Lee's moment bound)")
        return (not bad), bad

    def as_dict(self):
        return {"a": self.a, "b": self.b, "rho": self.rho, "m": self.m,
                "sigma": self.sigma, "rmse": self.rmse, "n_quotes": self.n_quotes}

    def __repr__(self):
        return (f"SVI(a={self.a:.5f}, b={self.b:.4f}, rho={self.rho:+.3f}, "
                f"m={self.m:+.4f}, sigma={self.sigma:.4f}, rmse={self.rmse*100:.2f}vp)")


def forward(spot: float, T: float, r: float = 0.04, q: float = 0.0) -> float:
    return spot * np.exp((r - q) * T)


def fit_svi(strikes, ivs, spot, T, r=0.04, q=0.0, weights=None) -> SVIParams | None:
    """Least-squares SVI fit of one expiry slice. None if it cannot be fit.

    Weighted in total-variance space. Vega weighting is the desk default --
    it stops far-wing quotes, which carry almost no information and the widest
    spreads, from dragging the fit around.
    """
    strikes = np.asarray(strikes, dtype=float)
    ivs = np.asarray(ivs, dtype=float)
    ok = np.isfinite(strikes) & np.isfinite(ivs) & (ivs > 0) & (strikes > 0)
    strikes, ivs = strikes[ok], ivs[ok]
    if len(strikes) < 5:
        return None

    F = forward(spot, T, r, q)
    k = np.log(strikes / F)
    w = (ivs ** 2) * T

    if weights is None:
        weights = bs.vega(spot, strikes, T, r, q, ivs)
    else:
        weights = np.asarray(weights, dtype=float)[ok]
    weights = np.nan_to_num(weights, nan=0.0)
    weights = weights / weights.max() if weights.max() > 0 else np.ones_like(w)
    weights = np.sqrt(np.maximum(weights, 1e-3))

    atm_var = float(np.interp(0.0, k, w)) if len(k) > 1 else float(w.mean())
    x0 = [max(atm_var * 0.5, 1e-4), 0.1, -0.7, 0.0, 0.1]
    lower = [-1.0, 0.0, -0.999, -2.0, 1e-4]
    upper = [10.0, 5.0, 0.999, 2.0, 5.0]

    def resid(p):
        a, b, rho, m, sig = p
        model = a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sig ** 2))
        return (model - w) * weights

    try:
        sol = least_squares(resid, x0, bounds=(lower, upper),
                            method="trf", max_nfev=4000)
    except Exception:
        return None
    if not sol.success and sol.status <= 0:
        return None

    p = SVIParams(*sol.x, n_quotes=len(k))
    # Report RMSE in VOL points, which is the unit traders think in.
    model_iv = p.iv(k, T)
    p.rmse = float(np.sqrt(np.mean((model_iv - ivs) ** 2)))
    return p


class SurfaceFits(dict):
    """Expiry -> fit mapping, carrying the reasons the others were rejected.

    Behaves as a plain dict so every consumer can iterate it normally, while
    `.rejected` explains the gaps. Silent omissions are how a surface tool
    quietly stops covering the expiry you care about.
    """

    def __init__(self, fits: dict, rejected: dict | None = None):
        super().__init__(fits)
        self.rejected = rejected or {}

    def explain(self) -> str:
        lines = [f"fitted {len(self)} expiries"]
        for exp, why in sorted(self.rejected.items()):
            lines.append(f"  rejected {pd.Timestamp(exp).date()}: {why}")
        return "\n".join(lines)


def otm_smile(grp: pd.DataFrame, F: float, max_k: float = 0.30,
              max_rel_spread: float = MAX_RELATIVE_SPREAD) -> pd.DataFrame:
    """Build the tradeable smile for one expiry: OTM quotes only.

    This construction is not a refinement, it is a correctness requirement.
    A deep ITM option is almost all intrinsic value, so its implied vol is
    hypersensitive to the mid: a one-cent quoting error on an option with two
    cents of time value throws the IV by tens of points. Feeding those into a
    least-squares fit lets the least reliable quotes in the chain dominate it.

    The market solves this by quoting the OTM side of each strike, and every
    real vol surface is built the same way: puts below the forward, calls above.

    Also drops quotes that are not real markets -- zero bid, absurd relative
    spread, or an IV outside any plausible band.
    """
    g = grp[
        grp["iv"].notna() & (grp["iv"] > 0.01) & (grp["iv"] < 3.0)
        & grp["mid"].notna() & (grp["mid"] > 0)
        & grp["bid"].notna() & (grp["bid"] > 0)
        & grp["ask"].notna() & (grp["ask"] > 0)
    ].copy()
    if g.empty:
        return g

    # OTM only: puts at or below the forward, calls above it.
    is_call = g["right"] == "C"
    g = g[((~is_call) & (g["strike"] <= F)) | (is_call & (g["strike"] > F))]
    if g.empty:
        return g

    g["rel_spread"] = (g["ask"] - g["bid"]) / g["mid"]
    g = g[g["rel_spread"] <= max_rel_spread]

    g["k"] = np.log(g["strike"] / F)
    g = g[g["k"].abs() <= max_k]

    # One quote per strike; OTM selection already made this near-unique.
    return g.sort_values("strike").drop_duplicates("strike", keep="first")


def fit_all_expiries(df: pd.DataFrame, spot: float, r: float = 0.04,
                     q: float = 0.0, min_quotes: int = 8,
                     max_k: float = 0.30, max_rmse: float = 0.02) -> dict:
    """Fit every expiry whose OTM smile is clean enough to be worth fitting.

    Fits with an RMSE above `max_rmse` (2 vol points) are REJECTED rather than
    returned. A bad fit is worse than no fit: every downstream residual is
    measured against it, so a wandering smile manufactures fake mispricings at
    every strike. Rejected expiries are recorded so the caller can say why.
    """
    fits, rejected = {}, {}
    for exp, grp in df.groupby("expiry"):
        T = float(grp["T"].iloc[0])
        F = forward(spot, T, r, q)
        g = otm_smile(grp, F, max_k=max_k)

        if len(g) < min_quotes:
            rejected[pd.Timestamp(exp)] = f"only {len(g)} clean OTM quotes"
            continue

        p = fit_svi(g["strike"], g["iv"], spot, T, r, q)
        if p is None:
            rejected[pd.Timestamp(exp)] = "SVI fit did not converge"
            continue

        arb_free, why = p.is_arbitrage_free()
        if p.rmse > max_rmse:
            rejected[pd.Timestamp(exp)] = f"fit RMSE {p.rmse*100:.1f} vol pts (limit {max_rmse*100:.0f})"
            continue
        if not arb_free:
            rejected[pd.Timestamp(exp)] = "fit violates no-arbitrage: " + "; ".join(why)
            continue

        fits[pd.Timestamp(exp)] = {"params": p, "T": T, "F": F,
                                   "n_quotes": int(len(g))}

    return SurfaceFits(fits, rejected)


# ======================================================================
# Relative value
# ======================================================================

def smile_residuals(df: pd.DataFrame, fits: dict, spot: float,
                    r: float = 0.04, q: float = 0.0) -> pd.DataFrame:
    """Per-contract richness against its own expiry's fitted smile.

    residual_vol > 0  quoted IV is ABOVE the smile -> the option is rich
    residual_vol < 0  quoted IV is BELOW the smile -> the option is cheap

    `edge_vs_model` converts that vol difference into dollars per contract via
    vega, which is what actually matters. A 3 vol point residual on a 2-day
    option is worth almost nothing; the same residual at 60 days is real money.
    """
    rows = []
    for exp, fit in fits.items():
        p, T, F = fit["params"], fit["T"], fit["F"]
        g = df[(df["expiry"] == exp) & df["iv"].notna() & (df["iv"] > 0)]
        if g.empty:
            continue
        k = np.log(g["strike"].to_numpy() / F)
        model_iv = p.iv(k, T)
        resid = g["iv"].to_numpy() - model_iv
        vega_ = bs.vega(spot, g["strike"].to_numpy(), T, r, q,
                        g["iv"].to_numpy()) / 100.0

        spread = g["ask"].to_numpy() - g["bid"].to_numpy()
        mid = g["mid"].to_numpy()
        rel_spread = np.where(mid > 0, spread / mid, np.inf)

        rows.append(pd.DataFrame({
            "expiry": exp,
            "dte": g["dte"].to_numpy(),
            "right": g["right"].to_numpy(),
            "strike": g["strike"].to_numpy(),
            "log_moneyness": k,
            "quoted_iv": g["iv"].to_numpy(),
            "model_iv": model_iv,
            "residual_vol": resid,
            "vega": vega_,
            "edge_vs_model": resid * vega_ * 100.0,   # $ per contract
            "bid": g["bid"].to_numpy(),
            "ask": g["ask"].to_numpy(),
            "mid": mid,
            "spread": spread,
            "rel_spread": rel_spread,
            "open_interest": g["open_interest"].to_numpy(),
            "volume": g["volume"].to_numpy(),
        }))

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["abs_edge"] = out["edge_vs_model"].abs()
    return out.sort_values("abs_edge", ascending=False).reset_index(drop=True)


def edge_after_costs(resid: pd.DataFrame, min_oi: float = 50,
                     min_edge_ratio: float = 1.0) -> pd.DataFrame:
    """Keep only candidates that survive crossing the spread.

    The test: to express a "cheap" view you must LIFT THE ASK, and to express a
    "rich" view you must HIT THE BID. So the real cost is half the spread on
    entry, and realistically half again on exit. `min_edge_ratio` is how many
    times that round-trip cost the model edge must be worth before a candidate
    is worth a human's attention. 1.0 is already generous.

    This function is the whole reason the module is trustworthy. Without it a
    residual screen produces a long list of illiquid strikes with stale quotes
    and calls them opportunities.
    """
    if resid.empty:
        return resid

    d = resid[
        (resid["open_interest"] >= min_oi)
        & (resid["rel_spread"] <= MAX_RELATIVE_SPREAD)
        & (resid["residual_vol"].abs() >= MIN_INTERESTING_RESIDUAL)
        & np.isfinite(resid["spread"])
        & (resid["spread"] > 0)
    ].copy()
    if d.empty:
        return d

    d["round_trip_cost"] = d["spread"] * 100.0          # $ per contract, in and out
    d["net_edge"] = d["abs_edge"] - d["round_trip_cost"]
    d["edge_ratio"] = d["abs_edge"] / d["round_trip_cost"]
    d["action"] = np.where(d["residual_vol"] > 0, "SELL (rich vs smile)",
                                                  "BUY (cheap vs smile)")
    d = d[d["edge_ratio"] >= min_edge_ratio]
    return d.sort_values("net_edge", ascending=False).reset_index(drop=True)


# ======================================================================
# Static arbitrage
# ======================================================================

def butterfly_arbitrage(df: pd.DataFrame, spot: float, expiry,
                        r: float = 0.04) -> list[dict]:
    """Detect convexity violations: C(K1) - 2*C(K2) + C(K3) < 0.

    A butterfly must cost something, because its payoff is non-negative. A
    negative cost is a genuine arbitrage -- and in practice, almost always a
    stale quote. Reported with the quotes attached so it can be checked by eye.
    """
    sub = df[(df["expiry"] == pd.Timestamp(expiry)) & (df["right"] == "C")]
    sub = sub[sub["mid"].notna()].sort_values("strike")
    if len(sub) < 3:
        return []

    K = sub["strike"].to_numpy()
    C = sub["mid"].to_numpy()
    bid = sub["bid"].to_numpy()
    ask = sub["ask"].to_numpy()

    out = []
    for i in range(len(K) - 2):
        k1, k2, k3 = K[i], K[i + 1], K[i + 2]
        # Weight so the payoff is a proper (possibly asymmetric) butterfly.
        wl = (k3 - k2) / (k3 - k1)
        wr = (k2 - k1) / (k3 - k1)
        cost = wl * C[i] - C[i + 1] + wr * C[i + 2]
        if cost < 0:
            # Re-price at executable prices: buy the wings, sell the body.
            exec_cost = wl * ask[i] - bid[i + 1] + wr * ask[i + 2]
            out.append({
                "type": "butterfly",
                "strikes": (float(k1), float(k2), float(k3)),
                "mid_cost": float(cost),
                "executable_cost": float(exec_cost),
                "real": bool(np.isfinite(exec_cost) and exec_cost < 0),
                "note": ("survives the spread -- verify the quotes manually"
                         if np.isfinite(exec_cost) and exec_cost < 0
                         else "mid-price only; disappears when you cross"),
            })
    return out


def calendar_arbitrage(fits: dict) -> list[dict]:
    """Total variance must be non-decreasing in maturity at fixed moneyness.

    w(k, T1) > w(k, T2) for T1 < T2 means the near expiry prices more total
    uncertainty than the far one at the same strike. Genuine violations are
    rare; near-dated event pricing (earnings, FOMC, CPI) produces apparent ones
    that are economically real, so these are reported as observations, not as
    free money.
    """
    if len(fits) < 2:
        return []
    ordered = sorted(fits.items(), key=lambda kv: kv[1]["T"])
    grid = np.linspace(-0.25, 0.25, 41)
    out = []
    for (e1, f1), (e2, f2) in zip(ordered, ordered[1:]):
        w1 = f1["params"].total_variance(grid)
        w2 = f2["params"].total_variance(grid)
        bad = grid[w1 > w2 + 1e-8]
        if len(bad):
            out.append({
                "type": "calendar",
                "near": str(pd.Timestamp(e1).date()),
                "far": str(pd.Timestamp(e2).date()),
                "log_moneyness_range": (float(bad.min()), float(bad.max())),
                "max_excess_variance": float(np.max(w1 - w2)),
                "note": "often genuine event pricing in the near expiry, not an arbitrage",
            })
    return out


# ======================================================================
# Risk-neutral density
# ======================================================================

def risk_neutral_density(params: SVIParams, F: float, T: float, r: float = 0.04,
                         k_range: float = 0.6, n: int = 401) -> pd.DataFrame:
    """Breeden-Litzenberger: the market's implied probability distribution.

        q(K) = exp(rT) * d2C/dK2

    Computed off the FITTED smile rather than raw quotes, because the second
    derivative of noisy market prices is unusable. This is the single most
    informative object in the whole module: it tells you what the option market
    actually believes about where the underlying can be, including the fat tails
    that a lognormal assumption misses entirely.
    """
    k = np.linspace(-k_range, k_range, n)
    K = F * np.exp(k)
    iv = params.iv(k, T)
    # Undiscounted Black-76 calls on the forward.
    C = bs.price(F, K, T, 0.0, 0.0, iv, "C")

    dK = np.gradient(K)
    d2C = np.gradient(np.gradient(C, K), K)
    dens = np.exp(r * T) * d2C
    dens = np.maximum(dens, 0.0)          # clip the numerical noise in the wings

    mass = np.sum(dens * dK)
    if mass > 0:
        dens = dens / mass                # normalise to a true density

    return pd.DataFrame({"strike": K, "log_moneyness": k, "iv": iv, "density": dens})


def density_stats(dens: pd.DataFrame, spot: float) -> dict:
    """Summarise the implied distribution in terms a trader can act on."""
    K = dens["strike"].to_numpy()
    p = dens["density"].to_numpy()
    dK = np.gradient(K)
    w = p * dK
    total = w.sum()
    if total <= 0:
        return {}
    w = w / total

    mean = float(np.sum(K * w))
    var = float(np.sum((K - mean) ** 2 * w))
    sd = float(np.sqrt(max(var, 0.0)))
    skew_ = float(np.sum(((K - mean) / sd) ** 3 * w)) if sd > 0 else float("nan")
    kurt = float(np.sum(((K - mean) / sd) ** 4 * w)) if sd > 0 else float("nan")

    cdf = np.cumsum(w)

    def q(pct):
        return float(np.interp(pct, cdf, K))

    return {
        "mean": mean,
        "mode": float(K[int(np.argmax(p))]),
        "std": sd,
        "skew": skew_,
        "excess_kurtosis": kurt - 3.0,
        "p05": q(0.05), "p25": q(0.25), "p50": q(0.50),
        "p75": q(0.75), "p95": q(0.95),
        "prob_above_spot": float(np.sum(w[K > spot])),
        "prob_below_spot": float(np.sum(w[K < spot])),
    }
