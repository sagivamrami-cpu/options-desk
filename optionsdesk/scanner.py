"""Candidate scanner: generate structures, score them, rank what survives.

This is the engine the agents drive. It does the heavy numerical work so an
LLM never has to: pull the chain, fit each expiry, build every plausible
structure, evaluate each against both densities, and return a ranked table.

Design decision worth stating: the scan is pure Python and carries no model.
Running an LLM every five minutes to recompute the same integrals would be
slow, expensive and less accurate. The agent's job starts where the scan ends
-- interpreting a short ranked list in the context of regime, positioning and
the user's actual risk tolerance.

GRID RESOLUTION
---------------
Expected value is computed by integrating a payoff against a numerical
density. A two-point-wide credit spread on a grid with 0.6-point spacing is
only three grid points wide, and its EV is then mostly interpolation error.
`_grid_for()` therefore derives spacing from the chain's own strike increment
rather than using a fixed point count, so narrow structures are resolved as
finely as wide ones.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd

from . import metrics as M
from . import structures as X
from . import surface as S
from .sources import fetch

__all__ = ["scan_symbol", "scan", "SCAN_COLUMNS"]

SCAN_COLUMNS = [
    "symbol", "expiry", "dte", "name", "structure", "cost", "slippage",
    "ev_empirical", "ev_risk_neutral", "edge", "edge_per_risk",
    "pop_empirical", "max_profit", "max_loss", "widest_rel_spread",
    "delta_shares", "vega_dollars", "theta_dollars_per_day",
]


def _grid_for(df: pd.DataFrame, expiry, spot: float, width: float = 0.40,
              subdivisions: int = 4, cap: int = 8000) -> np.ndarray:
    """Uniform strike grid fine enough to resolve the narrowest listed spread."""
    ks = np.sort(df[df["expiry"] == pd.Timestamp(expiry)]["strike"].unique())
    step = float(np.median(np.diff(ks))) if len(ks) > 2 else spot * 0.005
    step = max(step / subdivisions, spot * 1e-4)
    lo, hi = spot * (1 - width), spot * (1 + width)
    n = int((hi - lo) / step) + 1
    if n > cap:                      # keep the integral affordable on wide chains
        step = (hi - lo) / cap
        n = cap
    return lo + step * np.arange(n)


def _candidates(df, expiry, spot, aggressive: bool = False) -> list[X.Structure]:
    """The standard menu. Undefined-risk structures are included only when
    explicitly asked for, and are still excluded from the default ranking."""
    deltas = (0.30, 0.20, 0.16, 0.10)
    out = []
    out += X.generate_verticals(df, expiry, spot, "P", deltas, (1, 2, 3))
    out += X.generate_verticals(df, expiry, spot, "C", deltas, (1, 2, 3))
    out += X.generate_condors(df, expiry, spot, (0.20, 0.16, 0.10), (2, 3))
    out += X.generate_butterflies(df, expiry, spot, (1, 2, 3), "C")
    out += X.generate_butterflies(df, expiry, spot, (1, 2, 3), "P")
    if aggressive:
        out += X.generate_strangles(df, expiry, spot, (0.20, 0.16, 0.10))
    return out


def scan_symbol(symbol: str, source: str = "auto", max_expiries: int = 8,
                dte_range: tuple[float, float] = (0, 45), r: float = 0.04,
                aggressive: bool = False, include_calendars: bool = True,
                max_spread: float = 0.25) -> dict:
    """Full scan of one underlying. Returns candidates plus the context needed
    to interpret them."""
    snap = fetch(symbol, source=source, max_expiries=max_expiries)
    df = M.prepare(snap, r=r, q=0.0)
    spot = snap.spot
    fits = S.fit_all_expiries(df, spot, r=r)

    if not fits:
        return {"symbol": snap.symbol, "spot": spot, "asof": snap.asof.isoformat(),
                "source": snap.source, "candidates": pd.DataFrame(),
                "error": "no expiry produced a usable smile",
                "rejected": getattr(fits, "rejected", {})}

    lo, hi = dte_range
    usable = [e for e in fits if lo <= fits[e]["T"] * 365 <= hi]
    usable.sort(key=lambda e: fits[e]["T"])

    reports = []
    for exp in usable:
        f = fits[exp]
        grid = _grid_for(df, exp, spot)
        rnd = S.risk_neutral_density(f["params"], f["F"], f["T"], r=r,
                                     k_range=0.5, n=2001)
        rn = np.interp(grid, rnd["strike"], rnd["density"])
        emp = X.empirical_density(snap.history, spot, f["T"] * 365.0, grid,
                                  recenter_to=f["F"])

        for st in _candidates(df, exp, spot, aggressive):
            rn_res = X.evaluate(df, st, spot, grid, rn, fits, exp, r=r,
                                use_executable=True)
            if "error" in rn_res or not rn_res["tradeable"]:
                continue
            rec = {
                "symbol": snap.symbol, "expiry": str(pd.Timestamp(exp).date()),
                "dte": round(f["T"] * 365, 1), "name": st.name, "structure": str(st),
                "cost": rn_res["cost"], "slippage": rn_res["slippage"],
                "ev_risk_neutral": rn_res["ev"],
                "max_profit": rn_res["max_profit"], "max_loss": rn_res["max_loss"],
                "widest_rel_spread": rn_res["widest_rel_spread"],
                "breakevens": rn_res["breakevens"],
            }
            if emp.size:
                ep = X.evaluate(df, st, spot, grid, emp, fits, exp, r=r,
                                use_executable=True)
                rec["ev_empirical"] = ep["ev"]
                rec["pop_empirical"] = ep["pop"]
                rec["edge"] = ep["ev"] - rn_res["ev"]
            else:
                rec["ev_empirical"] = rec["edge"] = rec["pop_empirical"] = float("nan")
            rec.update(X.structure_greeks(df, st, spot))
            reports.append(rec)

    if include_calendars and len(usable) >= 2:
        for near, far in zip(usable, usable[1:]):
            grid = _grid_for(df, near, spot)
            f = fits[near]
            rnd = S.risk_neutral_density(f["params"], f["F"], f["T"], r=r,
                                         k_range=0.5, n=2001)
            rn = np.interp(grid, rnd["strike"], rnd["density"])
            emp = X.empirical_density(snap.history, spot, f["T"] * 365.0, grid,
                                      recenter_to=f["F"])
            for st in X.generate_calendars(df, near, far, spot, "C", (0, 1, -1)):
                rn_res = X.evaluate(df, st, spot, grid, rn, fits, near, r=r,
                                    use_executable=True)
                if "error" in rn_res or not rn_res["tradeable"]:
                    continue
                rec = {
                    "symbol": snap.symbol, "expiry": str(pd.Timestamp(near).date()),
                    "dte": round(f["T"] * 365, 1), "name": st.name, "structure": str(st),
                    "cost": rn_res["cost"], "slippage": rn_res["slippage"],
                    "ev_risk_neutral": rn_res["ev"],
                    "max_profit": rn_res["max_profit"], "max_loss": rn_res["max_loss"],
                    "widest_rel_spread": rn_res["widest_rel_spread"],
                    "breakevens": rn_res["breakevens"],
                }
                if emp.size:
                    ep = X.evaluate(df, st, spot, grid, emp, fits, near, r=r,
                                    use_executable=True)
                    rec["ev_empirical"] = ep["ev"]
                    rec["pop_empirical"] = ep["pop"]
                    rec["edge"] = ep["ev"] - rn_res["ev"]
                else:
                    rec["ev_empirical"] = rec["edge"] = rec["pop_empirical"] = float("nan")
                rec.update(X.structure_greeks(df, st, spot))
                reports.append(rec)

    cands = pd.DataFrame(reports)
    if not cands.empty:
        cands = cands[cands["widest_rel_spread"] <= max_spread]
        cands = cands[np.isfinite(cands["max_loss"]) & (cands["max_loss"] < 0)]
        cands["edge_per_risk"] = cands["edge"] / cands["max_loss"].abs()

        # A positive `edge` only says the structure is priced better than the
        # market's own measure implies. It does NOT say the trade makes money:
        # after crossing the spread the absolute expectation can still be
        # negative, and on wide-market underlyings it usually is. Rank on edge,
        # but state the absolute verdict so the two can never be confused.
        cands["verdict"] = np.where(
            cands["ev_empirical"] > 0, "positive expectancy",
            np.where(cands["edge"] > 0,
                     "better than market, still -EV after costs",
                     "negative"),
        )
        cands = cands.sort_values("edge_per_risk", ascending=False).reset_index(drop=True)

    # Relative value on individual contracts, for context.
    rv = S.edge_after_costs(S.smile_residuals(df, fits, spot, r=r), min_oi=50)

    return {
        "symbol": snap.symbol,
        "spot": spot,
        "asof": snap.asof.isoformat(timespec="seconds"),
        "source": snap.source,
        "warnings": snap.warnings,
        "n_fitted": len(fits),
        "rejected": getattr(fits, "rejected", {}),
        "carry": {str(pd.Timestamp(e).date()): round(f.get("implied_carry", 0.0), 5)
                  for e, f in fits.items()},
        "candidates": cands,
        "relative_value": rv,
        "regime": _regime(df, spot, fits, snap),
    }


def _regime(df, spot, fits, snap) -> dict:
    """Minimal regime context so a candidate is never read in isolation.

    A short-premium structure that looks good on edge alone is a different
    proposition when dealers are short gamma and realized vol is running above
    implied. The scan attaches that context to every result deliberately.
    """
    gex = M.gex_profile(df, spot)
    iv30 = None
    if fits:
        near = min(fits, key=lambda e: abs(fits[e]["T"] * 365 - 30))
        iv30 = float(fits[near]["params"].iv(0.0, fits[near]["T"]))
    rv20 = M.realized_vol(snap.history, 20)
    return {
        "gamma_regime": gex["regime"],
        "flip_level": gex["flip_level"],
        "spot_vs_flip_pct": gex["spot_vs_flip"],
        "net_gex": gex["total"],
        "iv30": iv30,
        "rv20": rv20,
        "vrp": (iv30 - rv20) if (iv30 is not None and np.isfinite(rv20)) else float("nan"),
    }


def scan(symbols=("GLD", "QQQ"), **kw) -> dict:
    out = {}
    for s in symbols:
        try:
            out[s.upper()] = scan_symbol(s, **kw)
        except Exception as exc:
            out[s.upper()] = {"symbol": s.upper(), "error": str(exc),
                              "candidates": pd.DataFrame()}
    return out
