#!/usr/bin/env python3
"""Daily options positioning report for gold and the Nasdaq.

    python scripts/daily_report.py                      # GLD + QQQ, auto source
    python scripts/daily_report.py --symbols QQQ,GLD,SPY
    python scripts/daily_report.py --source ibkr        # fail if TWS is down
    python scripts/daily_report.py --source yahoo       # skip IBKR entirely
    python scripts/daily_report.py --no-persist         # don't touch IV history

Writes out/report-YYYY-MM-DD.html and out/report-YYYY-MM-DD.json, and prints a
terminal digest. Exit code is non-zero only if EVERY symbol failed, so a single
bad ticker never kills a scheduled run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optionsdesk.render import render_dashboard          # noqa: E402
from optionsdesk.report import analyze, to_json          # noqa: E402
from optionsdesk.sources import fetch as fetch_snap       # noqa: E402

# Per-symbol carry assumptions. GLD holds bullion and pays no dividend -- its
# expense ratio is a small negative carry, which is close enough to zero.
CARRY = {
    "GLD": {"div_yield": 0.0},
    "QQQ": {"div_yield": 0.005},
    "SPY": {"div_yield": 0.012},
    "IWM": {"div_yield": 0.010},
    "SLV": {"div_yield": 0.0},
}
DEFAULT_SYMBOLS = ["GLD", "QQQ"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                   help="comma-separated tickers (default: GLD,QQQ)")
    p.add_argument("--source", default="auto", choices=["auto", "ibkr", "marketdata", "yahoo"])
    p.add_argument("--expiries", type=int, default=8, help="how many expiries to pull")
    p.add_argument("--rate", type=float, default=0.04, help="risk-free rate")
    p.add_argument("--out", default=str(ROOT / "out"))
    p.add_argument("--lang", default="he", choices=["he", "en"],
                   help="language for the Telegram digest (default Hebrew)")
    p.add_argument("--strategies", action="store_true", default=True,
                   help="include ranked structures with a management plan")
    p.add_argument("--no-strategies", dest="strategies", action="store_false")
    p.add_argument("--telegram", action="store_true",
                   help="send the digest to Telegram (scripts/setup_telegram.py)")
    p.add_argument("--no-persist", action="store_true",
                   help="skip appending to the IV history file")
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    analyses, failures, strategies = [], [], {}
    from optionsdesk.scanner import scan_symbol
    for sym in symbols:
        try:
            print(f"[{sym}] pulling chain via {args.source} …", flush=True)
            # ONE fetch per symbol, reused for the dashboard analysis, the
            # full strategy scan, and (below) the daily/weekly ledger status.
            # marketdata.app charges roughly a credit per contract returned;
            # three independent fetches of the same chain a few seconds apart
            # would triple the cost of every scheduled run for zero new
            # information.
            snap = fetch_snap(sym, source=args.source, max_expiries=args.expiries)
            a = analyze(
                sym, snap=snap, rate=args.rate,
                div_yield=CARRY.get(sym, {}).get("div_yield", 0.0),
                persist=not args.no_persist,
            )
            analyses.append(a)
            print(f"[{sym}] {a['read']['regime']} · "
                  f"GEX {a['gex']['total']:,.0f} · flip {a['gex']['flip_level']:.2f}",
                  flush=True)

            if args.strategies:
                strategies[sym] = scan_symbol(sym, snap=snap, dte_range=(0, 45))
        except Exception as exc:
            failures.append((sym, exc))
            print(f"[{sym}] FAILED: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    if not analyses:
        print("\nAll symbols failed — no report written.", file=sys.stderr)
        return 1

    html_path = out_dir / f"report-{today}.html"
    json_path = out_dir / f"report-{today}.json"
    html_path.write_text(
        render_dashboard(analyses, title=f"Options Desk — {today}"), encoding="utf-8"
    )
    to_json({"date": today, "symbols": analyses,
             "failures": [{"symbol": s, "error": str(e)} for s, e in failures]}, json_path)

    print(_digest(analyses, failures))
    print(f"\nHTML  {html_path}\nJSON  {json_path}")

    # Daily and weekly tracked recommendations: mark whatever is already open
    # to market, close what hit target/stop/expiry, and pick a fresh candidate
    # for any bucket left empty. Reuses each symbol's already-fetched scan --
    # no further API calls.
    desk_status = {}
    if args.strategies and strategies:
        from optionsdesk.deskrun import symbol_status
        from optionsdesk.ledger import Ledger
        ledger = Ledger()
        for sym, scan in strategies.items():
            try:
                desk_status[sym] = symbol_status(sym, scan, ledger, today=_dt.date.today())
            except Exception as exc:
                print(f"[{sym}] position tracking failed: {exc}", file=sys.stderr)

    from optionsdesk import events as ev_mod
    upcoming_events = ev_mod.upcoming(7)
    fresh = ev_mod.data_freshness()
    if fresh["needs_refresh"]:
        print(f"! event calendar has {fresh['events_remaining']} events left and needs "
              f"a refresh (source last checked {fresh['source_checked']})", file=sys.stderr)

    if args.telegram and analyses:
        from optionsdesk import notify
        try:
            if args.lang == "he":
                sent = notify.send_report_he(analyses, None, strategies, None,
                                             desk_status, upcoming_events)
            else:
                sent = notify.send_report(analyses, None, strategies)
            print("TG    sent" if sent else "TG    not configured -- run scripts/setup_telegram.py")
        except Exception as exc:
            # Delivery is not the job. A failed send must never lose the report.
            print(f"TG    failed: {exc}", file=sys.stderr)

    return 0


def _digest(analyses, failures) -> str:
    lines = ["", "=" * 66, "  DAILY OPTIONS POSITIONING", "=" * 66]
    for a in analyses:
        r, g, v = a["read"], a["gex"], a["vol"]
        flip = g["flip_level"]
        lines += [
            "",
            f"  {a['symbol']}  {a['spot']:,.2f}   [{a['source']}]",
            f"    regime    {r['regime']}  (tilt {r['tilt']})",
            f"    net GEX   {g['total']:>18,.0f}  per 1% move",
            f"    γ flip    {flip:>18,.2f}  spot {g['spot_vs_flip_pct']:+.2f}%"
            if flip == flip else "    γ flip    unavailable",
            f"    IV30/RV20 {v['iv30']*100:>17.1f}% / {v['rv20']*100:.1f}%"
            f"   VRP {v['vrp']['vrp']*100:+.1f} pts",
            f"    → {r['summary']}",
        ]
    if failures:
        lines += ["", "  FAILED: " + ", ".join(s for s, _ in failures)]
    lines += ["", "=" * 66]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
