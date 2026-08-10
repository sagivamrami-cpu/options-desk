"""Why a closed position won or lost, and whether that reason keeps repeating.

Two different claims, kept deliberately separate:

  explain_close       ONE trade's own mechanics, restated against what
                      actually happened -- how far spot moved, whether that
                      met the family's own stated condition for success, how
                      it closed. This is always available, for n=1.

  pattern_stats       a claim that a specific (symbol, family) combination
                      keeps winning or losing, which is not something one
                      trade can support. Same discipline the rest of this
                      project applies to any claimed edge: a group is only
                      reported once it has at least `min_n` independent
                      closes behind it, and the sample size is shown next to
                      every number rather than implied away.

Both return plain data, not rendered text -- same split as management.py
(plan_for/plan_he return field values; notify.py owns RLM, HTML-escaping and
bidi isolation for the Telegram message). Keeping that split here means the
post-mortem gets the same bidi-safety treatment as everything else instead
of a second, easy-to-forget implementation of it.

Nothing here guesses. Every field comes from data already on the Position
(entry/exit spot, final_pnl, close_reason, opened_at/closed_at) and the same
family-keyed Hebrew text management.py already uses for the forward-looking
plan -- so the post-mortem and the original plan can never contradict each
other, because they are the same text read backwards.
"""

from __future__ import annotations

import datetime as _dt

from . import management as M
from .ledger import Ledger, Position

__all__ = ["explain_close", "pattern_stats"]

CLOSE_REASON_HE = {
    "target": "נסגר ביעד",
    "stop": "נסגר בעצירה",
    "expired": "פקע",
}


def explain_close(pos: Position) -> dict:
    """Field values for one closed trade's post-mortem: what happened,
    whether the structure's own condition for success was met, and the same
    entry-check text as a lesson for next time -- restated, not reinvented,
    so it matches what the original recommendation already said to watch for.
    """
    fam = M._family(pos.name)
    pnl = pos.final_pnl or 0.0

    days_held = None
    try:
        opened = _dt.datetime.fromisoformat(pos.opened_at).date()
        closed = _dt.datetime.fromisoformat(pos.closed_at).date()
        days_held = (closed - opened).days
    except (TypeError, ValueError):
        pass

    move_pct = None
    if pos.exit_spot is not None and pos.entry_spot:
        move_pct = (pos.exit_spot - pos.entry_spot) / pos.entry_spot * 100.0

    return {
        "symbol": pos.symbol, "name": pos.name,
        "fam_he": M.FAMILY_HE.get(fam, "מבנה"),
        "reason_he": CLOSE_REASON_HE.get(pos.close_reason, pos.close_reason or "נסגר"),
        "days_held": days_held,
        "entry_spot": pos.entry_spot, "exit_spot": pos.exit_spot,
        "move_pct": move_pct,
        "final_pnl": pnl, "entry_cost": pos.entry_cost,
        "needs": M._NEEDS_HE.get(fam, M._DEFAULT_NEEDS_HE),
        "entry_check": M._ENTRY_HE.get(fam, M._DEFAULT_ENTRY_HE),
    }


def pattern_stats(ledger: Ledger, min_n: int = 3) -> list[dict]:
    """Win rate and average P&L per (symbol, family), for every combination
    with at least `min_n` closed trades behind it. Sorted worst win rate
    first, since that is the direction worth reading first.
    """
    closed = ledger.closed_positions()
    if not closed:
        return []

    groups: dict[tuple[str, str], list[Position]] = {}
    for p in closed:
        key = (p.symbol, M._family(p.name))
        groups.setdefault(key, []).append(p)

    out = []
    for (sym, fam), positions in groups.items():
        n = len(positions)
        if n < min_n:
            continue
        pnls = [p.final_pnl or 0.0 for p in positions]
        wins = sum(1 for x in pnls if x > 0)
        out.append({
            "symbol": sym, "family": fam, "n": n,
            "win_rate": wins / n,
            "avg_pnl": sum(pnls) / n,
            "total_pnl": sum(pnls),
        })
    out.sort(key=lambda r: r["win_rate"])
    return out
