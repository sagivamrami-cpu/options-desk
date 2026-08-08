"""Positioning and volatility metrics computed off a ChainSnapshot.

This is the analytical core. Everything here answers one of three questions:

  WHERE IS VOL?        iv_rank, term_structure, vol_risk_premium, realized_vol
  WHO IS POSITIONED?   gex_profile, vanna_charm, skew, put_call_ratios
  WHERE ARE THE PINS?  max_pain, oi_walls, expected_move

Dealer-sign convention used for every exposure number below is the market
standard (SqueezeMetrics): dealers are assumed NET LONG CALLS and NET SHORT
PUTS, because the flow they absorb is customers overwriting calls and buying
protective puts. Every exposure is therefore `calls - puts`.

That assumption is an approximation, not a fact. It holds well for index and
large-ETF products where retail and institutional hedging dominate, and it
breaks down when a single large customer runs the other way. Treat the numbers
as a positioning read, never as a forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import blackscholes as bs
from .sources.base import ChainSnapshot

CONTRACT_MULTIPLIER = 100
TRADING_DAYS = 252

# Reasonable defaults; override per-symbol in config.yaml.
DEFAULT_RATE = 0.04
DEFAULT_YIELD = 0.0


# ======================================================================
# Chain preparation
# ======================================================================

def prepare(snap: ChainSnapshot, r: float = DEFAULT_RATE,
            q: float = DEFAULT_YIELD, moneyness: float = 0.35) -> pd.DataFrame:
    """Clean the raw chain and attach greeks. Returns an enriched frame.

    Drops contracts that carry no information (no mid AND no open interest) and
    strikes outside +/- `moneyness` of spot, which contribute noise to the vol
    surface and essentially nothing to gamma.
    """
    df = snap.chain.copy()
    spot = snap.spot

    lo, hi = spot * (1 - moneyness), spot * (1 + moneyness)
    df = df[(df["strike"] >= lo) & (df["strike"] <= hi)]
    df = df[(df["mid"].notna()) | (df["open_interest"] > 0)]
    if df.empty:
        raise ValueError(f"{snap.symbol}: no usable contracts after cleaning")

    # Fill in any IV the source did not give us by inverting the mid price.
    need_iv = df["iv"].isna() & df["mid"].notna()
    if need_iv.any():
        sub = df.loc[need_iv]
        df.loc[need_iv, "iv"] = bs.implied_vol_chain(
            sub["mid"].to_numpy(), spot, sub["strike"].to_numpy(),
            sub["T"].to_numpy(), r, q, sub["right"].to_numpy(),
        )

    # Anything still without an IV cannot be given greeks; keep the row for OI
    # accounting but its greek contribution will be zero.
    df["iv"] = df["iv"].astype(float)
    valid = df["iv"].notna() & (df["iv"] > 0)

    for col in ("delta", "gamma", "vega", "theta", "vanna", "charm"):
        df[col] = 0.0

    if valid.any():
        v = df.loc[valid]
        S, K, T, sig, right = (
            spot, v["strike"].to_numpy(), v["T"].to_numpy(),
            v["iv"].to_numpy(), v["right"].to_numpy(),
        )
        df.loc[valid, "delta"] = bs.delta(S, K, T, r, q, sig, right)
        df.loc[valid, "gamma"] = bs.gamma(S, K, T, r, q, sig)
        df.loc[valid, "vega"] = bs.vega(S, K, T, r, q, sig) / 100.0      # per vol point
        df.loc[valid, "theta"] = bs.theta(S, K, T, r, q, sig, right) / 365.0  # per day
        df.loc[valid, "vanna"] = bs.vanna(S, K, T, r, q, sig)
        df.loc[valid, "charm"] = bs.charm(S, K, T, r, q, sig, right) / 365.0  # per day

    df["is_call"] = df["right"] == "C"
    df["notional_oi"] = df["open_interest"] * CONTRACT_MULTIPLIER * spot
    return df.reset_index(drop=True)


# ======================================================================
# Realized vol and the volatility risk premium
# ======================================================================

def realized_vol(history: pd.DataFrame, window: int = 20) -> float:
    """Annualised close-to-close realized volatility over `window` sessions."""
    if history is None or len(history) < window + 2:
        return float("nan")
    rets = np.log(history["close"]).diff().dropna()
    if len(rets) < window:
        return float("nan")
    return float(rets.tail(window).std(ddof=1) * np.sqrt(TRADING_DAYS))


def realized_vol_cone(history: pd.DataFrame, window: int = 20) -> dict:
    """Where does today's realized vol sit inside its own 1-year distribution?

    Useful on day one, before any IV history has accumulated: it answers "is
    this market unusually calm or unusually violent by its own standards".
    """
    if history is None or len(history) < window + 30:
        return {"current": float("nan"), "percentile": float("nan"),
                "min": float("nan"), "max": float("nan")}
    rets = np.log(history["close"]).diff().dropna()
    rolling = rets.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS)
    rolling = rolling.dropna()
    if rolling.empty:
        return {"current": float("nan"), "percentile": float("nan"),
                "min": float("nan"), "max": float("nan")}
    cur = float(rolling.iloc[-1])
    return {
        "current": cur,
        "percentile": float((rolling < cur).mean() * 100.0),
        "min": float(rolling.min()),
        "max": float(rolling.max()),
    }


def vol_risk_premium(atm_iv_: float, rv: float) -> dict:
    """IV minus RV -- what option sellers are being paid above what happened.

    Positive is the normal state (the structural edge). Persistent negative VRP
    means realized moves are outrunning what options price, which is the regime
    where premium selling gets carried out on a stretcher.
    """
    if not (np.isfinite(atm_iv_) and np.isfinite(rv)):
        return {"iv": atm_iv_, "rv": rv, "vrp": float("nan"), "ratio": float("nan")}
    return {
        "iv": atm_iv_, "rv": rv,
        "vrp": atm_iv_ - rv,
        "ratio": atm_iv_ / rv if rv > 0 else float("nan"),
    }


# ======================================================================
# The volatility surface
# ======================================================================

def atm_iv(df: pd.DataFrame, spot: float, expiry=None) -> float:
    """IV at the money, averaged across the call and put nearest spot."""
    sub = df if expiry is None else df[df["expiry"] == pd.Timestamp(expiry)]
    sub = sub[sub["iv"].notna() & (sub["iv"] > 0)]
    if sub.empty:
        return float("nan")
    out = []
    for _, side in sub.groupby("is_call"):
        idx = (side["strike"] - spot).abs().idxmin()
        out.append(float(side.loc[idx, "iv"]))
    return float(np.mean(out)) if out else float("nan")


def term_structure(df: pd.DataFrame, spot: float) -> pd.DataFrame:
    """ATM IV by expiry, plus the slope that classifies the regime.

    Upward sloping (contango) is the calm default: near-dated vol cheaper than
    far-dated. Inverted (backwardation) means the market is paying up for
    immediate protection -- that is a stress signature, and historically the
    condition under which short-premium books blow up.
    """
    rows = []
    for exp, grp in df.groupby("expiry"):
        iv = atm_iv(grp, spot)
        if np.isfinite(iv):
            rows.append({
                "expiry": exp,
                "dte": float(grp["dte"].iloc[0]),
                "atm_iv": iv,
                "total_oi": float(grp["open_interest"].sum()),
                "total_volume": float(grp["volume"].sum()),
            })
    ts = pd.DataFrame(rows).sort_values("dte").reset_index(drop=True)
    if len(ts) >= 2:
        near, far = ts.iloc[0], ts.iloc[-1]
        ts.attrs["slope"] = float(far["atm_iv"] - near["atm_iv"])
        ts.attrs["inverted"] = bool(far["atm_iv"] < near["atm_iv"])
    else:
        ts.attrs["slope"] = float("nan")
        ts.attrs["inverted"] = False
    return ts


def skew(df: pd.DataFrame, spot: float, expiry=None, target_delta: float = 0.25) -> dict:
    """25-delta risk reversal: put IV minus call IV at equal distance from ATM.

    In equity products this is essentially always positive -- crash insurance
    costs more than upside. What matters is the LEVEL versus its own norm:
    steepening means hedging demand is accelerating, flattening means either
    complacency or genuine upside chase.
    """
    sub = df if expiry is None else df[df["expiry"] == pd.Timestamp(expiry)]
    sub = sub[sub["iv"].notna() & (sub["iv"] > 0) & (sub["delta"] != 0)]
    if sub.empty:
        return {"put_iv": float("nan"), "call_iv": float("nan"),
                "skew": float("nan"), "atm_iv": float("nan")}

    calls = sub[sub["is_call"]]
    puts = sub[~sub["is_call"]]

    call_iv = _iv_at_delta(calls, target_delta)
    put_iv = _iv_at_delta(puts, -target_delta)
    atm = atm_iv(sub, spot)

    return {
        "put_iv": put_iv,
        "call_iv": call_iv,
        "skew": put_iv - call_iv if np.isfinite(put_iv) and np.isfinite(call_iv) else float("nan"),
        "atm_iv": atm,
    }


def _iv_at_delta(side: pd.DataFrame, target: float) -> float:
    """Linear-interpolate IV to an exact delta along one side of the surface."""
    if side.empty:
        return float("nan")
    s = side.sort_values("delta")
    d, iv = s["delta"].to_numpy(), s["iv"].to_numpy()
    if target < d.min() or target > d.max():
        # Outside the listed range -- fall back to the closest listed strike.
        return float(iv[np.abs(d - target).argmin()])
    return float(np.interp(target, d, iv))


# ======================================================================
# Dealer positioning
# ======================================================================

def gex_profile(df: pd.DataFrame, spot: float) -> dict:
    """Gamma exposure by strike, total, and the modelled zero-gamma flip level.

    Units: dollars of underlying dealers must trade per 1% move in spot.

    Reading it:
      total > 0  dealers long gamma -> they sell rallies and buy dips.
                 Vol gets suppressed, ranges hold, big strikes act as magnets.
      total < 0  dealers short gamma -> they buy rallies and sell dips.
                 Moves get amplified, trends extend, gaps become more likely.
      flip level the spot price where that behaviour reverses. Trading above or
                 below it is the single most useful regime read in this report.
    """
    scale = CONTRACT_MULTIPLIER * spot * spot * 0.01
    sign = np.where(df["is_call"], 1.0, -1.0)
    df = df.assign(gex=df["gamma"] * df["open_interest"] * scale * sign)

    by_strike = (df.groupby("strike")["gex"].sum()
                   .sort_index().rename("gex").reset_index())
    by_expiry = (df.groupby("expiry")["gex"].sum()
                   .sort_index().rename("gex").reset_index())

    total = float(df["gex"].sum())
    flip = _zero_gamma(df, spot)

    peaks = by_strike.reindex(by_strike["gex"].abs().sort_values(ascending=False).index)

    return {
        "total": total,
        "regime": "long_gamma" if total > 0 else "short_gamma",
        "flip_level": flip,
        "spot_vs_flip": (spot - flip) / spot * 100.0 if np.isfinite(flip) else float("nan"),
        "by_strike": by_strike,
        "by_expiry": by_expiry,
        "largest_positive": _peak(by_strike, "max"),
        "largest_negative": _peak(by_strike, "min"),
        "top_strikes": peaks.head(8).to_dict("records"),
    }


def _peak(by_strike: pd.DataFrame, how: str) -> dict:
    if by_strike.empty:
        return {"strike": float("nan"), "gex": float("nan")}
    idx = by_strike["gex"].idxmax() if how == "max" else by_strike["gex"].idxmin()
    row = by_strike.loc[idx]
    return {"strike": float(row["strike"]), "gex": float(row["gex"])}


def _zero_gamma(df: pd.DataFrame, spot: float, span: float = 0.15,
                steps: int = 121) -> float:
    """Find where aggregate dealer gamma crosses zero.

    Method: hold every contract's IV fixed (sticky-strike) and re-price gamma
    across a grid of hypothetical spot levels, then locate the sign change. This
    is the standard approach and it is a MODEL output -- it moves as OI changes,
    so it should be re-read daily rather than treated as a fixed line.
    """
    valid = df[(df["iv"] > 0) & df["iv"].notna() & (df["open_interest"] > 0)]
    if valid.empty:
        return float("nan")

    K = valid["strike"].to_numpy()
    T = valid["T"].to_numpy()
    sig = valid["iv"].to_numpy()
    oi = valid["open_interest"].to_numpy()
    sign = np.where(valid["is_call"].to_numpy(), 1.0, -1.0)

    grid = np.linspace(spot * (1 - span), spot * (1 + span), steps)
    totals = np.empty_like(grid)
    for i, s in enumerate(grid):
        g = bs.gamma(s, K, T, DEFAULT_RATE, DEFAULT_YIELD, sig)
        totals[i] = np.sum(g * oi * sign) * CONTRACT_MULTIPLIER * s * s * 0.01

    crossings = np.where(np.diff(np.sign(totals)) != 0)[0]
    if len(crossings) == 0:
        return float("nan")
    # Take the crossing closest to spot -- that is the one price is trading against.
    i = crossings[np.abs(grid[crossings] - spot).argmin()]
    x0, x1, y0, y1 = grid[i], grid[i + 1], totals[i], totals[i + 1]
    return float(x0 - y0 * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x0)


def vanna_charm(df: pd.DataFrame, spot: float) -> dict:
    """Aggregate dealer vanna and charm exposure.

    Vanna exposure: how many dollars of underlying dealers must trade for a
    1-point change in IV, with spot unchanged. This is the engine behind the
    "market drifts up for no reason after a scare" pattern -- as IV bleeds
    lower, short-vanna dealers mechanically buy.

    Charm exposure: the same, per day of time passing. Charm is why Thursday
    and Friday of an expiration week have a directional tilt of their own.
    """
    sign = np.where(df["is_call"], 1.0, -1.0)
    notional = df["open_interest"] * CONTRACT_MULTIPLIER * spot

    vanna_exp = float(np.sum(df["vanna"] * notional * sign) / 100.0)  # per 1 vol point
    charm_exp = float(np.sum(df["charm"] * notional * sign))          # per day

    return {
        "vanna": vanna_exp,
        "charm": charm_exp,
        "vanna_reading": (
            "IV falling mechanically generates dealer BUYING"
            if vanna_exp < 0 else
            "IV falling mechanically generates dealer SELLING"
        ),
        "charm_reading": (
            "time passing mechanically generates dealer BUYING"
            if charm_exp > 0 else
            "time passing mechanically generates dealer SELLING"
        ),
    }


def put_call_ratios(df: pd.DataFrame) -> dict:
    calls, puts = df[df["is_call"]], df[~df["is_call"]]
    c_oi, p_oi = float(calls["open_interest"].sum()), float(puts["open_interest"].sum())
    c_v, p_v = float(calls["volume"].sum()), float(puts["volume"].sum())
    return {
        "oi_ratio": p_oi / c_oi if c_oi else float("nan"),
        "volume_ratio": p_v / c_v if c_v else float("nan"),
        "call_oi": c_oi, "put_oi": p_oi,
        "call_volume": c_v, "put_volume": p_v,
    }


# ======================================================================
# Expiration mechanics
# ======================================================================

def max_pain(df: pd.DataFrame, expiry) -> dict:
    """The strike at which the least money is paid out to option holders.

    Computed honestly: for every candidate settlement price, total the intrinsic
    value owed across all open contracts and pick the minimum. Max pain is a
    weak magnet, not a law -- it is most informative when it sits far from spot
    into a monthly expiry with heavy open interest.
    """
    sub = df[(df["expiry"] == pd.Timestamp(expiry)) & (df["open_interest"] > 0)]
    if sub.empty:
        return {"strike": float("nan"), "payout": float("nan"), "curve": pd.DataFrame()}

    strikes = np.sort(sub["strike"].unique())
    calls = sub[sub["is_call"]]
    puts = sub[~sub["is_call"]]

    ck, coi = calls["strike"].to_numpy(), calls["open_interest"].to_numpy()
    pk, poi = puts["strike"].to_numpy(), puts["open_interest"].to_numpy()

    payouts = np.array([
        np.sum(np.maximum(0.0, s - ck) * coi) + np.sum(np.maximum(0.0, pk - s) * poi)
        for s in strikes
    ]) * CONTRACT_MULTIPLIER

    i = int(np.argmin(payouts))
    return {
        "strike": float(strikes[i]),
        "payout": float(payouts[i]),
        "curve": pd.DataFrame({"strike": strikes, "payout": payouts}),
    }


def expected_move(df: pd.DataFrame, spot: float, expiry) -> dict:
    """How far the option market says this thing can travel by `expiry`.

    Two independent readings, because they disagree in useful ways:
      sigma_move    spot * ATM IV * sqrt(T) -- the model's 1 standard deviation
      straddle      the actual cost of the ATM straddle, which is what you would
                    really pay. When the straddle implies more than sigma, the
                    surface is pricing a fat tail the lognormal model does not.
    """
    sub = df[df["expiry"] == pd.Timestamp(expiry)]
    if sub.empty:
        return {}

    T = float(sub["T"].iloc[0])
    dte = float(sub["dte"].iloc[0])
    iv = atm_iv(sub, spot)

    k = float(sub.iloc[(sub["strike"] - spot).abs().argmin()]["strike"])
    atm = sub[sub["strike"] == k]
    call = atm[atm["is_call"]]["mid"]
    put = atm[~atm["is_call"]]["mid"]
    straddle = (float(call.iloc[0]) if len(call) else np.nan) + \
               (float(put.iloc[0]) if len(put) else np.nan)

    sigma_move = spot * iv * np.sqrt(T) if np.isfinite(iv) else float("nan")

    return {
        "expiry": pd.Timestamp(expiry), "dte": dte, "atm_iv": iv,
        "atm_strike": k,
        "straddle_price": straddle,
        "straddle_pct": straddle / spot * 100.0 if np.isfinite(straddle) else float("nan"),
        "sigma_move": sigma_move,
        "sigma_pct": sigma_move / spot * 100.0 if np.isfinite(sigma_move) else float("nan"),
        "upper": spot + sigma_move if np.isfinite(sigma_move) else float("nan"),
        "lower": spot - sigma_move if np.isfinite(sigma_move) else float("nan"),
    }


def oi_walls(df: pd.DataFrame, expiry=None, n: int = 5) -> dict:
    """The strikes with the heaviest open interest -- support and resistance
    that exists because of hedging, not because of chart geometry."""
    sub = df if expiry is None else df[df["expiry"] == pd.Timestamp(expiry)]
    calls = (sub[sub["is_call"]].groupby("strike")["open_interest"].sum()
             .sort_values(ascending=False).head(n))
    puts = (sub[~sub["is_call"]].groupby("strike")["open_interest"].sum()
            .sort_values(ascending=False).head(n))
    return {
        "call_walls": [{"strike": float(k), "oi": float(v)} for k, v in calls.items()],
        "put_walls": [{"strike": float(k), "oi": float(v)} for k, v in puts.items()],
    }
