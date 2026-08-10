"""Orchestration: turn a scan into a professional-desk status update.

Ties the scanner (candidates), the ledger (persisted recommendations marked to
market) and the event calendar (does this expiry cross a scheduled print)
into the single object the daily report and the intraday watcher both render.

This is the layer where "here is a trade idea" becomes "here is how
yesterday's idea is doing, and whether the market has started moving against
it" -- a position is re-priced against the current chain rather than silently
re-proposed every day it happens to still be open, and a fresh idea is offered
only once the previous one has actually closed (by target, stop, or expiry).
"""

from __future__ import annotations

import datetime as _dt

from . import events as E
from .alerts import Alert
from .ledger import Ledger
from .scanner import pick_daily_weekly

__all__ = ["bucket_status", "symbol_status", "ledger_alerts"]


def bucket_status(symbol: str, bucket: str, scan: dict, ledger: Ledger,
                  today: _dt.date | None = None) -> dict:
    """Status for one symbol's daily or weekly slot.

    status='existing'  a tracked recommendation is still open; `mark` carries
                        its current P&L and whether it needs attention.
    status='new'        nothing was open (or the old one just closed), and a
                        fresh candidate cleared the cost test; it is recorded.
    status='none'       nothing open and nothing in this bucket clears costs.
    """
    today = today or _dt.date.today()
    df, spot = scan["_df"], scan["spot"]

    # Mark-to-market everything open for this symbol first (and auto-close
    # anything that hit target, stop, or expiry) before deciding whether this
    # bucket needs a fresh pick.
    marks = ledger.sweep_expired({symbol: df}, {symbol: spot}, today=today)
    still_open = [m for m in marks if m["position"].bucket == bucket
                  and m["position"].status == "open"]
    # Every element of `marks` came from a position that was open at the start
    # of THIS call, so "closed" here unambiguously means "closed just now".
    just_closed = [m for m in marks if m["position"].bucket == bucket
                  and m["position"].status == "closed"]

    picks = pick_daily_weekly(scan, today)
    target_expiry = picks[bucket]["target_expiry"]
    risk = E.expiry_risk(target_expiry, today) if target_expiry else None

    if still_open:
        return {"bucket": bucket, "status": "existing", "mark": still_open[0],
               "target_expiry": target_expiry, "event_risk": risk,
               "just_closed": just_closed}

    cand = picks[bucket]["candidate"]
    if cand is None:
        return {"bucket": bucket, "status": "none", "target_expiry": target_expiry,
               "event_risk": risk, "just_closed": just_closed}

    pos = ledger.record(symbol, bucket, cand.to_dict(), spot)
    return {"bucket": bucket, "status": "new", "position": pos, "candidate": cand,
           "target_expiry": target_expiry, "event_risk": risk,
           "just_closed": just_closed}


def symbol_status(symbol: str, scan: dict, ledger: Ledger,
                  today: _dt.date | None = None) -> dict:
    """Both buckets for one symbol. `scan` must include '_df' -- pass the dict
    scanner.scan_symbol() returns directly, not a stripped-down copy."""
    return {b: bucket_status(symbol, b, scan, ledger, today) for b in ("daily", "weekly")}


def ledger_alerts(status_by_symbol: dict) -> list[Alert]:
    """Turn a symbol_status() result into Alert objects for the SAME
    change-only pipeline the regime alerts use (optionsdesk.alerts / watch.py).

    Every event here is inherently one-shot, not level-based, so no extra
    "did this already fire" bookkeeping is needed on top of it:

      strike_crossings   ledger.mark_to_market only reports a crossing on the
                         pass where the side actually flips (see ledger.py);
                         it is silent on every pass before and after that.
      just_closed        `marks` inside bucket_status only contains positions
                         that were OPEN at the start of that sweep call, so a
                         'closed' status there was closed BY this call.
      status == 'new'    record() only fires when a bucket had nothing open;
                         once recorded, later passes see 'existing' instead.
    """
    out: list[Alert] = []
    for sym, buckets in status_by_symbol.items():
        for bucket, info in buckets.items():
            for closed in info.get("just_closed", []):
                p = closed["position"]
                sev = {"stop": "critical", "target": "warning",
                      "expired": "info"}.get(p.close_reason, "info")
                verb = {"stop": "hit its stop", "target": "hit its profit target",
                       "expired": "expired"}.get(p.close_reason, p.close_reason)
                out.append(Alert(sev, sym, f"position_{p.close_reason}",
                    f"{bucket} position '{p.name}' {verb} -- P&L ${closed['pnl']:+.0f}",
                    {"bucket": bucket, "pnl": closed["pnl"], "position_id": p.id}))

            mark = info.get("mark")
            if mark:
                p = mark["position"]
                for c in mark.get("strike_crossings", []):
                    out.append(Alert("critical", sym, "strike_crossed",
                        f"{bucket} position '{p.name}': spot crossed the short strike "
                        f"{c['strike']:g} ({c['from']} -> {c['to']}) -- thesis being tested",
                        {"bucket": bucket, "strike": c["strike"], "position_id": p.id}))

            if info.get("status") == "new":
                p = info["position"]
                side = "credit" if p.entry_cost < 0 else "debit"
                out.append(Alert("warning", sym, "new_recommendation",
                    f"new {bucket} idea: {p.name} ({p.expiry}), {side} "
                    f"${abs(p.entry_cost):.0f}, target ${p.target_pnl:.0f} / "
                    f"stop ${abs(p.stop_pnl):.0f}",
                    # name/expiry/cost/target/stop/legs duplicated here (not just
                    # in the English `message` above) because the Hebrew alert
                    # renderer builds its text from `detail` only, never from
                    # `message` -- without these fields it had no way to say
                    # WHICH structure was recorded, only that one was.
                    {"bucket": bucket, "position_id": p.id, "name": p.name,
                     "expiry": p.expiry, "cost": p.entry_cost,
                     "target_pnl": p.target_pnl, "stop_pnl": p.stop_pnl,
                     "legs": p.legs}))
    return out
