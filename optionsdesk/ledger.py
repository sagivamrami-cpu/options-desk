"""Position ledger: track a proposed structure from recommendation to close.

WHAT THIS IS AND IS NOT
------------------------
There is no brokerage integration here. Nothing in this project submits an
order or knows whether you actually took a trade. What this module tracks is
the SYSTEM'S OWN RECOMMENDATION: when the daily report proposes a specific
structure, it is recorded here, and every subsequent pass re-prices that exact
same structure against the current chain and reports how it is doing.

That is still genuinely useful, and it is the honest version of "track my
positions": a professional desk keeps a book of live ideas and marks them to
market whether or not every one was actually executed, because the discipline
of watching an idea play out is what produces the next good idea. Calling it
anything more than that -- claiming to know a real fill, a real account, a
real P&L -- would be a claim this system has no way to back up.

MARK-TO-MARKET IDENTITY
------------------------
    pnl = -(cost to open) - (cost to close now)

cost_to_open is what price_structure() returned when the position was
recorded: negative for a credit, positive for a debit. cost_to_close is what
price_structure() returns for the REVERSED legs against the CURRENT chain --
longs become shorts and vice versa, so pricing it naturally hits the bid to
sell what you own and lifts the ask to buy back what you sold, exactly as a
real close would. This automatically prices in both entry and exit slippage,
so an open position's paper P&L is never better than reality would give you.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import structures as X

__all__ = ["Position", "Ledger", "DEFAULT_PATH"]

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "positions" / "ledger.json"

# Mirrors management.GAMMA_DANGER_DTE; duplicated as a literal to keep this
# module import-independent of management.py's internals.
GAMMA_DANGER_DTE = 21


@dataclass
class Position:
    id: str
    symbol: str
    bucket: str                 # 'daily' | 'weekly'
    name: str
    legs: list                  # [{"expiry": "...", "right": "...", "strike": ..., "qty": ...}, ...]
    expiry: str                 # the position's own expiry (nearest leg for calendars)
    opened_at: str
    entry_spot: float
    entry_cost: float           # executable cost at open; <0 credit, >0 debit
    max_profit: float
    max_loss: float
    target_pnl: float
    stop_pnl: float
    status: str = "open"        # 'open' | 'closed'
    closed_at: str | None = None
    close_reason: str | None = None
    final_pnl: float | None = None
    exit_spot: float | None = None
    meta: dict = field(default_factory=dict)

    def to_structure(self) -> X.Structure:
        legs = [X.Leg(pd.Timestamp(l["expiry"]), l["right"], float(l["strike"]), int(l["qty"]))
               for l in self.legs]
        return X.Structure(self.name, legs, {"spot": self.entry_spot})

    def as_dict(self) -> dict:
        return asdict(self)


class Ledger:
    """JSON-backed store. Not a database -- a few open positions at a time,
    read and rewritten whole, which is simple enough to be trustworthy."""

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self._positions: dict[str, Position] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for d in raw:
            self._positions[d["id"]] = Position(**d)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([p.as_dict() for p in self._positions.values()],
                                  indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)          # atomic on POSIX

    # ------------------------------------------------------------------
    def open_positions(self, symbol: str | None = None, bucket: str | None = None
                       ) -> list[Position]:
        out = [p for p in self._positions.values() if p.status == "open"]
        if symbol:
            out = [p for p in out if p.symbol == symbol]
        if bucket:
            out = [p for p in out if p.bucket == bucket]
        return out

    def closed_positions(self, symbol: str | None = None) -> list[Position]:
        out = [p for p in self._positions.values() if p.status == "closed"]
        if symbol:
            out = [p for p in out if p.symbol == symbol]
        return out

    def record(self, symbol: str, bucket: str, candidate_row: dict,
              spot: float) -> Position:
        """Record a scanner candidate as a tracked recommendation.

        `candidate_row` is a row from scanner.scan_symbol()['candidates'], plus
        it must carry a `_legs` field -- see scanner.candidate_legs().
        """
        legs = candidate_row["_legs"]
        cost = float(candidate_row["cost"])
        max_p = float(candidate_row.get("max_profit", float("nan")))
        max_l = float(candidate_row.get("max_loss", float("nan")))

        # Delegate to management.py rather than keeping a second, independent
        # heuristic here. The two used to disagree: this method's old formula
        # (35% of max_profit for every debit structure) and management.py's
        # descriptive text ("75-100% of the debit" for a long straddle) were
        # computing different things from the same candidate, and a long
        # straddle's max_profit is a grid-truncation artifact in the first
        # place -- see target_stop_for()'s docstring for the number that
        # surfaced this.
        from .management import target_stop_for
        target, stop = target_stop_for(candidate_row)

        pos = Position(
            id=uuid.uuid4().hex[:12],
            symbol=symbol, bucket=bucket, name=candidate_row["name"],
            legs=legs, expiry=candidate_row["expiry"],
            opened_at=_dt.datetime.now().isoformat(timespec="seconds"),
            entry_spot=float(spot), entry_cost=cost,
            max_profit=max_p, max_loss=max_l,
            target_pnl=target, stop_pnl=stop,
            meta={"dte_at_open": candidate_row.get("dte"),
                 "pop_at_open": candidate_row.get("pop_empirical")},
        )
        self._positions[pos.id] = pos
        self._save()
        return pos

    def mark_to_market(self, pos: Position, df: pd.DataFrame, spot: float,
                       today: _dt.date | None = None) -> dict:
        """Re-price the exact recorded legs against the current chain."""
        today = today or _dt.date.today()
        struct = pos.to_structure()
        reversed_legs = [X.Leg(l.expiry, l.right, l.strike, -l.qty) for l in struct.legs]
        reversed_struct = X.Structure("close", reversed_legs)

        px = X.price_structure(df, reversed_struct)
        exp_date = _dt.date.fromisoformat(pos.expiry)
        dte_left = (exp_date - today).days

        if not px["tradeable"]:
            # Past expiry, or the strikes have rolled off the chain -- settle
            # to intrinsic instead of reporting a position with no market.
            grid = np.array([spot])
            value = X._value_at_horizon(struct, grid, pd.Timestamp(today), {}, r=0.04)[0] * X.MULT
            cost_to_close = -value
            priced_from = "intrinsic (no live quote for one or more legs)"
        else:
            cost_to_close = px["executable_cost"]
            priced_from = "live market"

        pnl = -pos.entry_cost - cost_to_close
        spot_move_pct = (spot - pos.entry_spot) / pos.entry_spot * 100.0

        pnl_of_target = pnl / pos.target_pnl if pos.target_pnl else float("nan")
        pnl_of_stop = pnl / pos.stop_pnl if pos.stop_pnl else float("nan")

        hit_target = pos.target_pnl > 0 and pnl >= pos.target_pnl
        hit_stop = pos.stop_pnl < 0 and pnl <= pos.stop_pnl
        expired = dte_left <= 0

        # Strike-side crossing: "the market started moving against the thesis"
        # made concrete and one-time, the same pattern as the gamma-flip
        # alert -- fire once on the crossing, not on every pass the position
        # happens to sit on the wrong side. Only short strikes are tracked:
        # those are the ones whose test actually threatens the position: a
        # short put being approached from above is the risk, a long put is not.
        short_strikes = sorted({l.strike for l in struct.legs if l.qty < 0 and l.right in ("C", "P")})
        sides = dict(pos.meta.get("strike_side", {}))
        crossings = []
        for k in short_strikes:
            side = "above" if spot > k else "below"
            prev = sides.get(str(k))
            if prev is not None and prev != side:
                crossings.append({"strike": k, "from": prev, "to": side})
            sides[str(k)] = side
        pos.meta["strike_side"] = sides

        return {
            "position": pos, "pnl": pnl, "cost_to_close": cost_to_close,
            "priced_from": priced_from, "spot": spot,
            "spot_move_pct": spot_move_pct, "dte_left": dte_left,
            "pnl_pct_of_target": pnl_of_target * 100 if np.isfinite(pnl_of_target) else float("nan"),
            "pnl_pct_of_stop": pnl_of_stop * 100 if np.isfinite(pnl_of_stop) else float("nan"),
            "hit_target": hit_target, "hit_stop": hit_stop, "expired": expired,
            "in_gamma_window": 0 < dte_left <= GAMMA_DANGER_DTE,
            "action_needed": hit_target or hit_stop or expired,
            "strike_crossings": crossings,
        }

    def close(self, pos: Position, reason: str, final_pnl: float,
             exit_spot: float | None = None):
        pos.status = "closed"
        pos.closed_at = _dt.datetime.now().isoformat(timespec="seconds")
        pos.close_reason = reason
        pos.final_pnl = final_pnl
        pos.exit_spot = exit_spot
        self._save()

    def sweep_expired(self, df_by_symbol: dict, spot_by_symbol: dict,
                      today: _dt.date | None = None) -> list[dict]:
        """Mark-to-market every open position; close what has hit target,
        stop, or expiry. Returns the mark for every position touched, open or
        just closed, so a caller can report on all of it."""
        today = today or _dt.date.today()
        out = []
        for pos in list(self.open_positions()):
            df = df_by_symbol.get(pos.symbol)
            spot = spot_by_symbol.get(pos.symbol)
            if df is None or spot is None:
                continue
            mark = self.mark_to_market(pos, df, spot, today)
            out.append(mark)
            if mark["hit_target"]:
                self.close(pos, "target", mark["pnl"], exit_spot=spot)
            elif mark["hit_stop"]:
                self.close(pos, "stop", mark["pnl"], exit_spot=spot)
            elif mark["expired"]:
                self.close(pos, "expired", mark["pnl"], exit_spot=spot)
        self._save()          # persist strike_side / meta updates on still-open positions
        return out
