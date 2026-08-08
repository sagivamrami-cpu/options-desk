"""Orchestration: snapshot in, structured analysis out.

`analyze()` produces a plain dict that both the HTML renderer and the agent
consume. Nothing in here decides what to trade -- it decides what the option
market is currently SAYING, and hands that to a human or an agent to interpret.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import metrics as M
from .sources import fetch

HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "history"

# IV rank needs a year of daily observations to mean anything. Below this we
# report it as unavailable rather than quoting a rank off six data points.
MIN_IV_HISTORY = 20


# ======================================================================
def analyze(symbol: str, source: str = "auto", max_expiries: int = 8,
            rate: float = M.DEFAULT_RATE, div_yield: float = M.DEFAULT_YIELD,
            persist: bool = True) -> dict:
    snap = fetch(symbol, source=source, max_expiries=max_expiries)
    df = M.prepare(snap, r=rate, q=div_yield)
    spot = snap.spot

    ts = M.term_structure(df, spot)
    front = ts.iloc[0] if len(ts) else None

    # The 30-day point is the industry reference tenor for "the" IV of a name.
    iv30 = _interp_atm_iv(ts, 30.0)
    rv20 = M.realized_vol(snap.history, 20)
    rv_cone = M.realized_vol_cone(snap.history, 20)

    gex = M.gex_profile(df, spot)
    vc = M.vanna_charm(df, spot)
    pcr = M.put_call_ratios(df)
    sk_front = M.skew(df, spot, front["expiry"] if front is not None else None)
    sk_all = M.skew(df, spot)

    # Per-expiry expiration mechanics for the nearest few dates.
    exp_detail = []
    for _, row in ts.head(4).iterrows():
        mp = M.max_pain(df, row["expiry"])
        em = M.expected_move(df, spot, row["expiry"])
        walls = M.oi_walls(df, row["expiry"])
        exp_detail.append({
            "expiry": str(pd.Timestamp(row["expiry"]).date()),
            "dte": float(row["dte"]),
            "atm_iv": float(row["atm_iv"]),
            "total_oi": float(row["total_oi"]),
            "total_volume": float(row["total_volume"]),
            "max_pain": float(mp["strike"]),
            "max_pain_dist_pct": (mp["strike"] - spot) / spot * 100.0 if np.isfinite(mp["strike"]) else float("nan"),
            "expected_move": em,
            "walls": walls,
            "skew": M.skew(df, spot, row["expiry"]),
        })

    history_stats = _update_history(symbol, snap.asof, spot, iv30, rv20,
                                    gex["total"], gex["flip_level"], persist=persist)

    result = {
        "symbol": snap.symbol,
        "asof": snap.asof.isoformat(timespec="seconds"),
        "source": snap.source,
        "warnings": snap.warnings,
        "spot": spot,
        "contracts_analyzed": int(len(df)),
        "vol": {
            "iv30": iv30,
            "rv20": rv20,
            "vrp": M.vol_risk_premium(iv30, rv20),
            "rv_cone": rv_cone,
            "iv_rank": history_stats["iv_rank"],
            "iv_percentile": history_stats["iv_percentile"],
            "iv_history_days": history_stats["days"],
            "term_structure": ts.assign(expiry=ts["expiry"].astype(str)).to_dict("records"),
            "term_slope": ts.attrs.get("slope", float("nan")),
            "inverted": ts.attrs.get("inverted", False),
        },
        "skew": {"front": sk_front, "aggregate": sk_all},
        "gex": {
            "total": gex["total"],
            "regime": gex["regime"],
            "flip_level": gex["flip_level"],
            "spot_vs_flip_pct": gex["spot_vs_flip"],
            "largest_positive": gex["largest_positive"],
            "largest_negative": gex["largest_negative"],
            "top_strikes": gex["top_strikes"],
            "profile": gex["by_strike"].to_dict("records"),
        },
        "flows": {**vc, "put_call": pcr},
        "expiries": exp_detail,
        "read": None,   # filled below
    }
    result["read"] = synthesize(result)
    return result


# ======================================================================
def synthesize(a: dict) -> dict:
    """Turn the numbers into an explicit, falsifiable positioning read.

    Deliberately NOT a price target. Each line states what the mechanics favour
    and why, so a human can disagree with a specific input rather than with an
    opaque score.
    """
    spot = a["spot"]
    gex, vol, flows = a["gex"], a["vol"], a["flows"]
    signals, bull, bear = [], 0, 0

    # --- 1. Gamma regime: the dominant read ---------------------------
    flip = gex["flip_level"]
    if gex["regime"] == "long_gamma":
        signals.append({
            "factor": "Gamma regime",
            "state": "Dealers long gamma",
            "meaning": "Hedging is mean-reverting: rallies get sold, dips get bought. "
                       "Expect range-bound, suppressed realized vol, strikes acting as magnets.",
            "bias": "range",
        })
    else:
        signals.append({
            "factor": "Gamma regime",
            "state": "Dealers short gamma",
            "meaning": "Hedging amplifies moves: rallies get bought, dips get sold. "
                       "Expect larger ranges, trend persistence, higher gap risk.",
            "bias": "volatile",
        })

    if np.isfinite(flip):
        above = spot > flip
        signals.append({
            "factor": "Zero-gamma flip",
            "state": f"Spot {'above' if above else 'below'} flip at {flip:,.2f} "
                     f"({(spot - flip) / spot * 100:+.2f}%)",
            "meaning": ("Stability zone. Losing this level flips dealers short gamma "
                        "and typically opens up the downside."
                        if above else
                        "Instability zone. Reclaiming this level would restore the "
                        "vol-suppressing regime."),
            "bias": "bullish" if above else "bearish",
        })
        bull += 1 if above else 0
        bear += 0 if above else 1

    # --- 2. Volatility risk premium -----------------------------------
    vrp = vol["vrp"]["vrp"]
    if np.isfinite(vrp):
        rich = vrp > 0
        signals.append({
            "factor": "Volatility risk premium",
            "state": f"IV30 {vol['iv30']*100:.1f}% vs RV20 {vol['rv20']*100:.1f}% "
                     f"(VRP {vrp*100:+.1f} pts)",
            "meaning": ("Options are pricing more movement than is being realized -- the "
                        "normal state, and the condition that pays premium sellers."
                        if rich else
                        "Realized movement is outrunning what options price. Premium "
                        "selling is being underpaid for the risk it carries."),
            "bias": "range" if rich else "volatile",
        })

    # --- 3. Term structure --------------------------------------------
    if vol["inverted"]:
        signals.append({
            "factor": "Term structure",
            "state": "Inverted (backwardation)",
            "meaning": "Near-dated vol is bid above far-dated. The market is paying up for "
                       "immediate protection -- a stress signature, not a calm one.",
            "bias": "bearish",
        })
        bear += 1
    elif np.isfinite(vol["term_slope"]):
        signals.append({
            "factor": "Term structure",
            "state": f"Normal contango (+{vol['term_slope']*100:.1f} pts front to back)",
            "meaning": "Calm baseline. No urgency being priced into near-dated protection.",
            "bias": "bullish",
        })
        bull += 1

    # --- 4. Skew -------------------------------------------------------
    sk = a["skew"]["front"]["skew"]
    if np.isfinite(sk):
        steep = sk > 0.05
        signals.append({
            "factor": "25-delta skew (front)",
            "state": f"{sk*100:+.1f} vol points (put over call)",
            "meaning": ("Steep. Downside insurance is expensive relative to upside -- "
                        "active hedging demand. At extremes this becomes contrarian."
                        if steep else
                        "Flat by equity standards. Little urgency in downside hedging; "
                        "can indicate complacency."),
            "bias": "bearish" if steep else "neutral",
        })
        if steep:
            bear += 1

    # --- 5. Vanna / charm ---------------------------------------------
    signals.append({
        "factor": "Vanna exposure",
        "state": f"${flows['vanna']:,.0f} per vol point",
        "meaning": flows["vanna_reading"] +
                   " -- this is the mechanical drift that appears after a vol spike fades.",
        "bias": "bullish" if flows["vanna"] < 0 else "bearish",
    })
    bull += 1 if flows["vanna"] < 0 else 0
    bear += 0 if flows["vanna"] < 0 else 1

    signals.append({
        "factor": "Charm exposure",
        "state": f"${flows['charm']:,.0f} per day",
        "meaning": flows["charm_reading"] +
                   " -- strongest into the last two sessions before a monthly expiry.",
        "bias": "bullish" if flows["charm"] > 0 else "bearish",
    })

    # --- 6. Put/call ---------------------------------------------------
    pcr_oi = flows["put_call"]["oi_ratio"]
    if np.isfinite(pcr_oi):
        signals.append({
            "factor": "Put/call open interest",
            "state": f"{pcr_oi:.2f}",
            "meaning": ("Put-heavy book. Usually protective positioning rather than a bearish "
                        "directional bet -- and it is fuel for a vanna rally if vol drops."
                        if pcr_oi > 1.2 else
                        "Call-heavy or balanced book. Less hedging ballast underneath the market."),
            "bias": "neutral",
        })

    # --- Regime label ---------------------------------------------------
    # Two INDEPENDENT axes, and they routinely disagree. Gamma says how price
    # will behave; VRP says whether options are priced fairly for that behaviour.
    # Collapsing them into one verdict is how you end up recommending premium
    # selling into a market that is realizing more than it implies.
    long_gamma = gex["regime"] == "long_gamma"
    vrp_positive = np.isfinite(vrp) and vrp > 0
    conflict = None

    if long_gamma and not vol["inverted"] and vrp_positive:
        regime = "Pinned / vol-suppressed"
        summary = ("Dealer hedging works against movement and options are paid above what is "
                   "being realized. The one regime where short premium is being compensated: "
                   "favour range structures and fade extremes toward the large gamma strikes.")
    elif long_gamma and not vrp_positive:
        regime = "Pinned but underpriced"
        summary = ("Dealers dampen moves, yet realized volatility is running ABOVE implied. "
                   "The pin is real but you are not being paid to sell it. Favour long-premium "
                   "structures, calendars and debit spreads over naked short premium.")
        conflict = ("Gamma positioning says range-bound; the volatility risk premium says "
                    "options are cheap. Respect the pin for direction, not for premium selling.")
    elif not long_gamma and vol["inverted"]:
        regime = "Stressed / trend-amplifying"
        summary = ("Dealer hedging feeds moves and near-dated vol is bid above far-dated. This is "
                   "the regime where short-premium books break. Defined risk and long convexity only.")
    elif not long_gamma:
        regime = "Unstable"
        summary = ("Dealers amplify rather than dampen. Expect wider ranges than the recent past; "
                   "size down short premium and treat the flip level as the line that matters.")
    else:
        regime = "Mixed"
        summary = ("Positioning is supportive but the vol surface is showing tension. "
                   "Trade smaller and lean on defined-risk structures.")

    tilt = "constructive" if bull > bear else "cautious" if bear > bull else "balanced"

    return {
        "regime": regime,
        "tilt": tilt,
        "bull_count": bull,
        "bear_count": bear,
        "summary": summary,
        "conflict": conflict,
        "signals": signals,
        "caveat": ("Every exposure number assumes dealers are long calls and short puts. "
                   "That is the standard convention, not observed truth. This is a read on "
                   "positioning and mechanics -- it is not a price forecast."),
    }


# ======================================================================
def _interp_atm_iv(ts: pd.DataFrame, target_dte: float) -> float:
    """ATM IV at a constant-maturity tenor, interpolated in variance space
    (which is how vol actually adds across time)."""
    if ts.empty:
        return float("nan")
    if len(ts) == 1:
        return float(ts.iloc[0]["atm_iv"])
    d = ts["dte"].to_numpy()
    var = (ts["atm_iv"].to_numpy() ** 2) * d
    if target_dte <= d[0]:
        return float(ts.iloc[0]["atm_iv"])
    if target_dte >= d[-1]:
        return float(ts.iloc[-1]["atm_iv"])
    v = np.interp(target_dte, d, var)
    return float(math.sqrt(v / target_dte))


def _update_history(symbol: str, asof, spot, iv30, rv20, gex_total, flip,
                    persist: bool = True) -> dict:
    """Append today's observation and compute IV rank/percentile from the file.

    IV rank is meaningless on day one. The report says so explicitly rather than
    quoting a number built from a handful of rows -- a fake 50 is worse than an
    honest "still accumulating".
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{symbol.upper()}_iv.csv"

    row = {
        "date": pd.Timestamp(asof).date().isoformat(),
        "spot": spot, "iv30": iv30, "rv20": rv20,
        "gex_total": gex_total, "flip": flip,
    }

    hist = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=list(row))
    if persist:
        hist = hist[hist["date"] != row["date"]]        # one row per day, last wins
        hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
        hist = hist.sort_values("date").tail(400)
        hist.to_csv(path, index=False)

    series = pd.to_numeric(hist.get("iv30", pd.Series(dtype=float)), errors="coerce").dropna()
    if len(series) < MIN_IV_HISTORY or not np.isfinite(iv30):
        return {"iv_rank": None, "iv_percentile": None, "days": int(len(series))}

    lo, hi = float(series.min()), float(series.max())
    rank = (iv30 - lo) / (hi - lo) * 100.0 if hi > lo else float("nan")
    return {
        "iv_rank": float(rank),
        "iv_percentile": float((series < iv30).mean() * 100.0),
        "days": int(len(series)),
    }


# ======================================================================
def to_json(analysis: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis, indent=2, default=_encode), encoding="utf-8")
    return path


def _encode(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if not math.isfinite(v) else v
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, (pd.Timestamp, _dt.datetime, _dt.date)):
        return str(o)
    if isinstance(o, pd.DataFrame):
        return o.to_dict("records")
    return str(o)
