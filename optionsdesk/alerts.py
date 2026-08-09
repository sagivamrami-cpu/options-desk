"""Alert rules: decide when a scan is worth a human's attention.

The reason this module exists is economic. A scan takes five seconds of CPU and
costs nothing; waking a language model to narrate an unchanged market every
five minutes costs money and trains you to ignore the output. So the scanner
runs constantly and this module decides, from the numbers alone, whether
anything actually happened.

Every rule below fires on a STATE CHANGE or a THRESHOLD CROSSING, never on a
level. "Dealers are long gamma" is not news at 10:05 if it was also true at
10:00. "Spot just crossed below the gamma flip" is news exactly once.

Severity is about how fast the state can hurt you, not how interesting it is:

  critical  the mechanical regime just changed, or is about to
  warning   a condition that changes what you should be doing
  info      worth knowing, safe to read later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

__all__ = ["Alert", "evaluate", "SEVERITY_ORDER"]

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Inside this distance from the flip, dealer hedging can reverse on a normal
# intraday swing, so the regime is effectively unstable rather than "long".
FLIP_PROXIMITY_PCT = 0.60


@dataclass
class Alert:
    severity: str
    symbol: str
    kind: str
    message: str
    detail: dict

    def to_dict(self):
        return asdict(self)

    def __str__(self):
        return f"[{self.severity.upper():8s}] {self.symbol} {self.kind}: {self.message}"


def _f(x, default=float("nan")):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def evaluate(scan: dict, previous: pd.Series | dict | None = None) -> list[Alert]:
    """Compare one scan against the previous observation and emit what changed.

    `previous` is a row from the intraday CSV, or None on the first pass of a
    session. With no previous state only the threshold rules can fire, which is
    correct: a crossing needs two points to exist.
    """
    out: list[Alert] = []
    sym = scan.get("symbol", "?")
    if "error" in scan:
        return [Alert("critical", sym, "scan_failed", scan["error"], {})]

    reg = scan.get("regime", {})
    spot = _f(scan.get("spot"))
    flip = _f(reg.get("flip_level"))
    dist = _f(reg.get("spot_vs_flip_pct"))
    vrp = _f(reg.get("vrp"))
    gamma_regime = reg.get("gamma_regime")

    prev = dict(previous) if previous is not None else {}
    p_dist = _f(prev.get("spot_vs_flip_pct"))
    p_vrp = _f(prev.get("vrp"))
    p_regime = prev.get("regime")

    # --- 1. Gamma flip crossing: the single most consequential change -------
    if math.isfinite(dist) and math.isfinite(p_dist) and dist * p_dist < 0:
        crossed_down = dist < 0
        out.append(Alert(
            "critical", sym, "gamma_flip_crossed",
            f"spot crossed {'BELOW' if crossed_down else 'ABOVE'} the gamma flip "
            f"at {flip:,.2f} (now {dist:+.2f}%)",
            {"flip": flip, "spot": spot, "from_pct": p_dist, "to_pct": dist,
             "implication": (
                 "dealer hedging now AMPLIFIES moves: rallies bought, dips sold. "
                 "Expect wider ranges and higher gap risk; size down short premium."
                 if crossed_down else
                 "dealer hedging now DAMPENS moves: rallies sold, dips bought. "
                 "Ranges should hold better and large strikes start acting as magnets.")},
        ))

    # --- 2. Sitting on the flip --------------------------------------------
    elif math.isfinite(dist) and abs(dist) < FLIP_PROXIMITY_PCT:
        was_far = math.isfinite(p_dist) and abs(p_dist) >= FLIP_PROXIMITY_PCT
        if was_far or not math.isfinite(p_dist):
            out.append(Alert(
                "critical", sym, "at_gamma_flip",
                f"spot is only {dist:+.2f}% from the flip at {flip:,.2f} -- "
                f"the regime can reverse on a normal intraday swing",
                {"flip": flip, "spot": spot, "distance_pct": dist},
            ))

    # --- 3. Regime label change --------------------------------------------
    if gamma_regime and p_regime and gamma_regime != p_regime:
        out.append(Alert(
            "critical", sym, "gamma_regime_change",
            f"net dealer gamma flipped {p_regime} -> {gamma_regime}",
            {"net_gex": _f(reg.get("net_gex")), "from": p_regime, "to": gamma_regime},
        ))

    # --- 4. Volatility risk premium sign change ----------------------------
    if math.isfinite(vrp) and math.isfinite(p_vrp) and vrp * p_vrp < 0:
        turned_negative = vrp < 0
        out.append(Alert(
            "warning", sym, "vrp_sign_change",
            f"VRP turned {'NEGATIVE' if turned_negative else 'POSITIVE'} "
            f"({vrp*100:+.1f} vol points)",
            {"vrp": vrp, "iv30": _f(reg.get("iv30")), "rv20": _f(reg.get("rv20")),
             "implication": (
                 "realized movement is now outrunning implied -- selling premium is "
                 "being underpaid for the risk it carries"
                 if turned_negative else
                 "implied is back above realized -- the usual state, and the one "
                 "that pays premium sellers")},
        ))

    # --- 5. A structure that actually clears costs -------------------------
    #
    # This rule keys off a CHANGE, like every other one here. An earlier version
    # fired whenever a positive-expectancy structure existed, which meant it
    # re-sent an identical alert every five minutes for as long as the condition
    # held. That is precisely how an alert channel becomes noise that gets
    # ignored -- and an ignored channel is worse than no channel, because you
    # believe you are being watched.
    cands = scan.get("candidates")
    if cands is not None and len(cands) and "ev_empirical" in cands:
        good = cands[cands["ev_empirical"] > 0]
        n_now = len(good)
        n_before = _f(prev.get("n_positive_ev"), default=-1.0)
        best_before = _f(prev.get("best_ev"), default=float("nan"))

        if n_now:
            best = good.iloc[0]
            best_ev = _f(best["ev_empirical"])

            appeared = n_before == 0                       # none last pass, some now
            first_look = n_before < 0                      # no previous state at all
            # A materially better opportunity than the one already reported.
            improved = (math.isfinite(best_before) and best_before > 0
                        and best_ev > best_before * 1.5 and best_ev - best_before > 10)

            if appeared or first_look or improved:
                why = ("first scan of the session" if first_look
                       else "newly appeared" if appeared
                       else f"materially better than the ${best_before:.2f} already reported")
                out.append(Alert(
                    "warning" if not first_look else "info", sym, "positive_expectancy",
                    f"{n_now} structure(s) clear costs ({why}); best: {best['name']} "
                    f"{best['expiry']} EV ${best_ev:+.2f} on ${abs(_f(best['max_loss'])):,.0f} risk",
                    {"count": int(n_now), "reason": why,
                     "best": {k: (float(best[k])
                                  if isinstance(best[k], (int, float, np.floating))
                                  else str(best[k]))
                              for k in ("name", "expiry", "cost", "ev_empirical", "edge",
                                        "pop_empirical", "max_loss", "slippage")
                              if k in best}},
                ))
        elif n_before > 0:
            out.append(Alert(
                "info", sym, "opportunity_gone",
                f"the {int(n_before)} structure(s) that cleared costs no longer do",
                {"was": int(n_before)},
            ))

    # --- 6. Term structure inversion ---------------------------------------
    if reg.get("inverted") and not prev.get("inverted", False):
        out.append(Alert(
            "warning", sym, "term_structure_inverted",
            "near-dated vol is now bid above far-dated -- a stress signature",
            {},
        ))

    # --- 7. Data quality ----------------------------------------------------
    rejected = scan.get("rejected") or {}
    if len(rejected) >= 3:
        out.append(Alert(
            "info", sym, "fit_quality",
            f"{len(rejected)} expiries could not be fitted; surface coverage is thin",
            {"rejected": {str(k): v for k, v in rejected.items()}},
        ))

    out.sort(key=lambda a: SEVERITY_ORDER.get(a.severity, 9))
    return out


def format_digest(alerts: list[Alert]) -> str:
    """One-screen summary. Empty string when there is nothing to say -- callers
    use that to decide whether to notify at all."""
    if not alerts:
        return ""
    lines = []
    for a in alerts:
        lines.append(str(a))
        imp = a.detail.get("implication")
        if imp:
            lines.append(f"           -> {imp}")
    return "\n".join(lines)
