"""Option structures: construction, pricing, greeks and honest expected value.

This module builds multi-leg positions and evaluates them. The evaluation is
where most retail "strategy finders" quietly cheat, so read this part carefully.

THE CENTRAL FACT ABOUT EXPECTED VALUE
--------------------------------------
Under the risk-neutral density recovered from option prices, the expected
profit of EVERY structure is zero minus transaction costs. That is not an
empirical finding, it is the definition of the density: it is the measure that
reprices every listed option back to its own market price. Integrating a
payoff against it just returns the price you paid.

So a screen that "finds high expected value using the greeks and the implied
distribution" is either measuring its own numerical error or lying.

A real edge requires a distribution that DIFFERS from the market's, and there
are only three honest sources for one:

  1. EMPIRICAL   -- what the underlying has actually done historically.
                    The gap between this and the risk-neutral density IS the
                    variance risk premium, and harvesting it is the single
                    best-documented structural edge in options.
  2. A VIEW      -- your own forecast, stated explicitly as a distribution so
                    it can be argued with and later scored.
  3. MISPRICING  -- one contract out of line with its own smile, which
                    surface.py finds and which almost never survives costs.

`evaluate()` therefore takes the density as a REQUIRED argument. There is no
default, because choosing it is the entire analytical act. `edge_report()`
runs a structure against both the risk-neutral and the empirical density and
reports the difference, which is the only number here that means anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import blackscholes as bs
from . import surface as S

__all__ = [
    "Leg", "Structure", "price_structure", "structure_greeks",
    "empirical_density", "evaluate", "edge_report",
    "generate_verticals", "generate_butterflies", "generate_condors",
    "generate_strangles", "generate_calendars", "rank",
]

MULT = 100


# ======================================================================
@dataclass(frozen=True)
class Leg:
    """One contract. qty > 0 is long, qty < 0 is short."""
    expiry: pd.Timestamp
    right: str          # 'C' or 'P'
    strike: float
    qty: int = 1

    def intrinsic(self, spot):
        spot = np.asarray(spot, dtype=float)
        if self.right == "C":
            return np.maximum(spot - self.strike, 0.0)
        return np.maximum(self.strike - spot, 0.0)

    def __str__(self):
        side = "+" if self.qty > 0 else "-"
        return f"{side}{abs(self.qty)} {pd.Timestamp(self.expiry).date()} {self.strike:g}{self.right}"


@dataclass
class Structure:
    name: str
    legs: list[Leg]
    meta: dict = field(default_factory=dict)

    @property
    def expiries(self):
        return sorted({pd.Timestamp(l.expiry) for l in self.legs})

    @property
    def is_calendar(self):
        return len(self.expiries) > 1

    def __str__(self):
        return f"{self.name}: " + "  ".join(str(l) for l in self.legs)


# ======================================================================
# Pricing
# ======================================================================

def _quote(df: pd.DataFrame, leg: Leg) -> pd.Series | None:
    m = df[(df["expiry"] == pd.Timestamp(leg.expiry))
           & (df["right"] == leg.right)
           & (np.isclose(df["strike"], leg.strike))]
    return None if m.empty else m.iloc[0]


def price_structure(df: pd.DataFrame, struct: Structure) -> dict:
    """Cost at mid and at prices you could actually transact.

    `executable` is the number that matters: longs lift the ask, shorts hit the
    bid. The gap between mid and executable is the entry cost, and it is
    subtracted from every edge estimate downstream.

    Positive cost = net debit (you pay). Negative = net credit (you receive).
    """
    mid_cost = exec_cost = 0.0
    missing, widest = [], 0.0

    for leg in struct.legs:
        q = _quote(df, leg)
        if q is None or not np.isfinite(q["mid"]):
            missing.append(str(leg))
            continue
        mid_cost += leg.qty * float(q["mid"])
        bid, ask = float(q["bid"]), float(q["ask"])
        if not (np.isfinite(bid) and np.isfinite(ask) and ask > 0):
            missing.append(str(leg))
            continue
        exec_cost += leg.qty * (ask if leg.qty > 0 else bid)
        if float(q["mid"]) > 0:
            widest = max(widest, (ask - bid) / float(q["mid"]))

    return {
        "mid_cost": mid_cost * MULT,
        "executable_cost": exec_cost * MULT,
        "slippage": (exec_cost - mid_cost) * MULT,
        "widest_rel_spread": widest,
        "missing_legs": missing,
        "tradeable": not missing,
    }


def structure_greeks(df: pd.DataFrame, struct: Structure, spot: float) -> dict:
    """Net position greeks, in the units a risk report uses."""
    g = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0,
         "vanna": 0.0, "charm": 0.0}
    for leg in struct.legs:
        q = _quote(df, leg)
        if q is None:
            continue
        for k in g:
            v = q.get(k, 0.0)
            if np.isfinite(v):
                g[k] += leg.qty * float(v)
    # Delta in shares, gamma as shares per 1% move, vega $/vol point, theta $/day.
    return {
        "delta_shares": g["delta"] * MULT,
        "gamma_shares_per_pct": g["gamma"] * MULT * spot * 0.01,
        "vega_dollars": g["vega"] * MULT,
        "theta_dollars_per_day": g["theta"] * MULT,
        "vanna": g["vanna"] * MULT,
        "charm": g["charm"] * MULT,
    }


# ======================================================================
# Densities
# ======================================================================

def empirical_density(history: pd.DataFrame, spot: float, horizon_days: float,
                      grid: np.ndarray, lookback: int = 500,
                      block: bool = True) -> np.ndarray:
    """The distribution the underlying has ACTUALLY produced, not the one
    options price.

    Built from overlapping N-day log returns over `lookback` sessions, applied
    to today's spot, then smoothed into a density on `grid`.

    Overlapping windows are used deliberately: they use the sample far more
    efficiently than disjoint blocks, at the cost of autocorrelated
    observations. That inflates confidence, not the central estimate, so it is
    acceptable here where the output is a shape rather than a p-value.

    The honest limitation: this is the past. It contains the crashes that
    happened and none of the ones that did not. For short horizons on liquid
    ETFs it is a reasonable base rate; for tail-risk questions it understates.
    """
    if history is None or len(history) < 60:
        return np.array([])

    closes = history["close"].astype(float).tail(lookback).to_numpy()
    n = max(int(round(horizon_days)), 1)
    if len(closes) <= n + 10:
        return np.array([])

    if block:
        rets = np.log(closes[n:] / closes[:-n])          # overlapping N-day
    else:
        idx = np.arange(0, len(closes) - n, n)
        rets = np.log(closes[idx + n] / closes[idx])
    rets = rets[np.isfinite(rets)]
    if len(rets) < 30:
        return np.array([])

    terminal = spot * np.exp(rets)

    # Gaussian KDE with Silverman bandwidth, evaluated on the supplied grid.
    sd = terminal.std(ddof=1)
    if sd <= 0:
        return np.array([])
    h = 1.06 * sd * len(terminal) ** (-1 / 5)
    z = (grid[:, None] - terminal[None, :]) / h
    dens = np.exp(-0.5 * z ** 2).sum(axis=1) / (len(terminal) * h * np.sqrt(2 * np.pi))

    area = np.trapezoid(dens, grid) if hasattr(np, "trapezoid") else np.trapz(dens, grid)
    return dens / area if area > 0 else dens


# ======================================================================
# Evaluation
# ======================================================================

def _value_at_horizon(struct: Structure, grid: np.ndarray, horizon: pd.Timestamp,
                      fits: dict, r: float = 0.04, q: float = 0.0) -> np.ndarray:
    """Per-share value of the structure at `horizon` across a grid of spots.

    Legs expiring at or before the horizon settle to intrinsic. Legs expiring
    later are re-priced with Black-Scholes using the IV their own expiry's
    fitted smile implies at that strike -- which is what makes calendars and
    diagonals evaluable at all, rather than only at final expiry.

    Sticky-strike is assumed for the surviving legs: each keeps the IV of its
    own strike as spot moves. That is the conservative convention for short-
    dated equity structures; sticky-delta would flatter long-vega positions.
    """
    total = np.zeros_like(grid, dtype=float)
    horizon = pd.Timestamp(horizon)

    for leg in struct.legs:
        exp = pd.Timestamp(leg.expiry)
        if exp <= horizon:
            total += leg.qty * leg.intrinsic(grid)
            continue

        fit = fits.get(exp)
        T_rem = max((exp - horizon).days / 365.0, 1e-4)
        if fit is None:
            total += leg.qty * leg.intrinsic(grid)      # no smile: intrinsic floor
            continue

        F = grid * np.exp((r - q) * T_rem)
        k = np.log(leg.strike / F)
        iv = fit["params"].iv(k, fit["T"])
        iv = np.clip(iv, 0.01, 3.0)
        total += leg.qty * bs.price(grid, leg.strike, T_rem, r, q, iv, leg.right)

    return total


def evaluate(df: pd.DataFrame, struct: Structure, spot: float,
             density_grid: np.ndarray, density: np.ndarray,
             fits: dict | None = None, horizon: pd.Timestamp | None = None,
             use_executable: bool = True, r: float = 0.04) -> dict:
    """Score a structure against a SUPPLIED distribution.

    There is no default density on purpose -- see the module docstring. Pass
    the risk-neutral one to sanity-check (EV should land near zero), and the
    empirical one to estimate real edge.
    """
    px = price_structure(df, struct)
    cost = px["executable_cost"] if use_executable else px["mid_cost"]

    horizon = pd.Timestamp(horizon) if horizon is not None else struct.expiries[0]
    T_h = max((horizon - pd.Timestamp.now().normalize()).days, 0) / 365.0

    # Discount the horizon value back to today so it is comparable with a cost
    # paid today. Without this the comparison mixes present and future value and
    # every EV inherits a spurious carry term.
    value = _value_at_horizon(struct, density_grid, horizon, fits or {}, r=r) * MULT
    pnl = value * np.exp(-r * T_h) - cost

    w = density * np.gradient(density_grid)
    total = w.sum()
    if total <= 0:
        return {"error": "degenerate density"}
    # How much probability mass the grid actually spans. Renormalising a
    # truncated density silently deletes the tail where short-premium
    # structures take their losses, which flatters them enormously.
    captured = float(total)
    w = w / total

    ev = float(np.sum(pnl * w))
    pop = float(np.sum(w[pnl > 0]))
    max_p, max_l = float(pnl.max()), float(pnl.min())

    sign = np.sign(pnl)
    flips = np.where(np.diff(sign) != 0)[0]
    breakevens = [float(np.interp(0, [pnl[i], pnl[i + 1]],
                                  [density_grid[i], density_grid[i + 1]]))
                  for i in flips if pnl[i] != pnl[i + 1]]

    downside = pnl[pnl < 0]
    wd = w[pnl < 0]
    exp_loss = float(np.sum(downside * wd) / wd.sum()) if wd.sum() > 0 else 0.0

    return {
        "structure": str(struct),
        "name": struct.name,
        "cost": cost,
        "mid_cost": px["mid_cost"],
        "slippage": px["slippage"],
        "tradeable": px["tradeable"],
        "widest_rel_spread": px["widest_rel_spread"],
        "ev": ev,
        "pop": pop,
        "max_profit": max_p,
        "max_loss": max_l,
        "breakevens": sorted(breakevens),
        "expected_loss_given_loss": exp_loss,
        # Risk-adjusted: EV per dollar genuinely at risk. Capped structures have
        # a real max loss; undefined-risk ones are reported as inf and excluded
        # from ranking rather than being flattered by a finite grid edge.
        "ev_per_risk": ev / abs(max_l) if max_l < 0 else float("inf"),
        "horizon": str(horizon.date()),
        "mass_captured": captured,
    }


def edge_report(df: pd.DataFrame, struct: Structure, spot: float,
                history: pd.DataFrame, fits: dict, r: float = 0.04,
                grid_width: float = 0.45, n: int = 401) -> dict:
    """Run one structure against BOTH densities. The gap is the edge estimate.

    ev_risk_neutral   should sit near minus the transaction cost. A large
                      positive value means a pricing or numerical error, not
                      an opportunity -- it is a diagnostic, not a signal.
    ev_empirical      expected P&L if the future resembles the sampled past.
    edge              the difference. This is the variance risk premium as it
                      applies to THIS structure, in dollars.
    """
    horizon = struct.expiries[0]
    T = max((pd.Timestamp(horizon) - pd.Timestamp.now().normalize()).days, 1) / 365.0

    fit = fits.get(pd.Timestamp(horizon))
    if fit is None:
        return {"error": f"no fitted smile for {pd.Timestamp(horizon).date()}"}

    # Evaluate on the density's OWN grid rather than resampling onto a narrower
    # one. Any grid that does not span the full risk-neutral support truncates
    # the loss tail, and short-premium structures then price as free money.
    rnd = S.risk_neutral_density(fit["params"], fit["F"], fit["T"], r=r,
                                 k_range=grid_width, n=n)
    grid = rnd["strike"].to_numpy()
    rn_dens = rnd["density"].to_numpy()
    emp = empirical_density(history, spot, T * 365.0, grid)

    out = {"structure": str(struct), "name": struct.name}
    rn = evaluate(df, struct, spot, grid, rn_dens, fits, horizon, r=r)
    out.update({k: rn[k] for k in ("cost", "slippage", "tradeable", "max_profit",
                                   "max_loss", "breakevens", "widest_rel_spread")})
    out["ev_risk_neutral"] = rn.get("ev")
    out["pop_risk_neutral"] = rn.get("pop")

    if emp.size:
        ep = evaluate(df, struct, spot, grid, emp, fits, horizon, r=r)
        out["ev_empirical"] = ep.get("ev")
        out["pop_empirical"] = ep.get("pop")
        out["edge"] = ep.get("ev", np.nan) - rn.get("ev", np.nan)
        out["ev_per_risk"] = ep.get("ev_per_risk")
    else:
        out["ev_empirical"] = out["edge"] = out["pop_empirical"] = float("nan")
        out["note"] = "not enough history for an empirical density"

    out["greeks"] = structure_greeks(df, struct, spot)
    return out


# ======================================================================
# Generators
# ======================================================================

def _strikes(df, expiry, right, spot, width=0.15, min_oi=25):
    g = df[(df["expiry"] == pd.Timestamp(expiry)) & (df["right"] == right)
           & (df["open_interest"] >= min_oi) & df["mid"].notna() & (df["bid"] > 0)]
    g = g[(g["strike"] >= spot * (1 - width)) & (g["strike"] <= spot * (1 + width))]
    return np.sort(g["strike"].unique())


def generate_verticals(df, expiry, spot, right="P", short_deltas=(0.30, 0.20, 0.16, 0.10),
                       widths=(1, 2, 3), min_oi=25):
    """Credit spreads at conventional short deltas. The 16-delta short strike is
    the desk default because it is roughly the 1-sigma point."""
    g = df[(df["expiry"] == pd.Timestamp(expiry)) & (df["right"] == right)
           & (df["open_interest"] >= min_oi) & (df["bid"] > 0)]
    if g.empty:
        return []
    ks = np.sort(g["strike"].unique())
    out = []
    for target in short_deltas:
        sub = g.copy()
        sub["dd"] = (sub["delta"].abs() - target).abs()
        short_k = float(sub.sort_values("dd").iloc[0]["strike"])
        i = int(np.where(ks == short_k)[0][0])
        for wdt in widths:
            j = i - wdt if right == "P" else i + wdt
            if not (0 <= j < len(ks)):
                continue
            long_k = float(ks[j])
            out.append(Structure(
                f"{'bull put' if right == 'P' else 'bear call'} spread {short_k:g}/{long_k:g}",
                [Leg(expiry, right, short_k, -1), Leg(expiry, right, long_k, +1)],
                {"short_delta_target": target, "width": abs(short_k - long_k)},
            ))
    return out


def generate_butterflies(df, expiry, spot, wings=(1, 2, 3), right="C", min_oi=25):
    ks = _strikes(df, expiry, right, spot, min_oi=min_oi)
    if len(ks) < 5:
        return []
    body = float(ks[np.abs(ks - spot).argmin()])
    i = int(np.where(ks == body)[0][0])
    out = []
    for w in wings:
        if i - w < 0 or i + w >= len(ks):
            continue
        lo, hi = float(ks[i - w]), float(ks[i + w])
        out.append(Structure(
            f"butterfly {lo:g}/{body:g}/{hi:g}",
            [Leg(expiry, right, lo, +1), Leg(expiry, right, body, -2),
             Leg(expiry, right, hi, +1)],
            {"wing_width": w},
        ))
    return out


def generate_condors(df, expiry, spot, short_deltas=(0.20, 0.16, 0.10),
                     widths=(2, 3), min_oi=25):
    """Iron condors: short strangle with long wings capping both tails."""
    out = []
    for d in short_deltas:
        puts = generate_verticals(df, expiry, spot, "P", (d,), widths, min_oi)
        calls = generate_verticals(df, expiry, spot, "C", (d,), widths, min_oi)
        for p, c in zip(puts, calls):
            out.append(Structure(
                f"iron condor {d:.0%}d w{p.meta['width']:g}",
                p.legs + c.legs,
                {"short_delta_target": d},
            ))
    return out


def generate_strangles(df, expiry, spot, short_deltas=(0.20, 0.16, 0.10), min_oi=25):
    """Short strangles. Undefined risk -- included so the ranking can show what
    you are being paid for taking it, not as a recommendation."""
    out = []
    for d in short_deltas:
        legs = []
        for right in ("P", "C"):
            g = df[(df["expiry"] == pd.Timestamp(expiry)) & (df["right"] == right)
                   & (df["open_interest"] >= min_oi) & (df["bid"] > 0)].copy()
            if g.empty:
                break
            g["dd"] = (g["delta"].abs() - d).abs()
            legs.append(Leg(expiry, right, float(g.sort_values("dd").iloc[0]["strike"]), -1))
        if len(legs) == 2:
            out.append(Structure(f"short strangle {d:.0%}d", legs,
                                 {"short_delta_target": d, "undefined_risk": True}))
    return out


def generate_calendars(df, near, far, spot, right="C", offsets=(0,), min_oi=25):
    ks = _strikes(df, near, right, spot, min_oi=min_oi)
    ks_far = _strikes(df, far, right, spot, min_oi=min_oi)
    common = np.intersect1d(ks, ks_far)
    if not len(common):
        return []
    atm = float(common[np.abs(common - spot).argmin()])
    i = int(np.where(common == atm)[0][0])
    out = []
    for o in offsets:
        j = i + o
        if not (0 <= j < len(common)):
            continue
        k = float(common[j])
        out.append(Structure(
            f"calendar {k:g}{right} {pd.Timestamp(near).date()}/{pd.Timestamp(far).date()}",
            [Leg(near, right, k, -1), Leg(far, right, k, +1)],
            {"offset": o},
        ))
    return out


# ======================================================================
def rank(reports: list[dict], require_defined_risk: bool = True,
         min_pop: float = 0.0, max_spread: float = 0.25) -> pd.DataFrame:
    """Order candidates by edge per dollar at risk, after filtering.

    Undefined-risk structures are excluded by default. Their max loss on a
    finite grid is an artefact of where the grid ends, so any risk-adjusted
    ranking that includes them is comparing a real number to a made-up one.
    """
    rows = [r for r in reports if "error" not in r and r.get("tradeable")]
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)

    d = d[d["widest_rel_spread"] <= max_spread]
    if require_defined_risk:
        d = d[np.isfinite(d["max_loss"]) & (d["max_loss"] < 0)]
    if min_pop > 0 and "pop_empirical" in d:
        d = d[d["pop_empirical"].fillna(0) >= min_pop]
    if d.empty:
        return d

    d["edge_per_risk"] = d["edge"] / d["max_loss"].abs()
    return d.sort_values("edge_per_risk", ascending=False).reset_index(drop=True)
