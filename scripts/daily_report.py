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
    p.add_argument("--source", default="auto", choices=["auto", "ibkr", "yahoo"])
    p.add_argument("--expiries", type=int, default=8, help="how many expiries to pull")
    p.add_argument("--rate", type=float, default=0.04, help="risk-free rate")
    p.add_argument("--out", default=str(ROOT / "out"))
    p.add_argument("--telegram", action="store_true",
                   help="send the digest to Telegram (scripts/setup_telegram.py)")
    p.add_argument("--no-persist", action="store_true",
                   help="skip appending to the IV history file")
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    analyses, failures = [], []
    for sym in symbols:
        try:
            print(f"[{sym}] pulling chain via {args.source} …", flush=True)
            a = analyze(
                sym,
                source=args.source,
                max_expiries=args.expiries,
                rate=args.rate,
                div_yield=CARRY.get(sym, {}).get("div_yield", 0.0),
                persist=not args.no_persist,
            )
            analyses.append(a)
            print(f"[{sym}] {a['read']['regime']} · "
                  f"GEX {a['gex']['total']:,.0f} · flip {a['gex']['flip_level']:.2f}",
                  flush=True)
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

    if args.telegram and analyses:
        from optionsdesk import notify
        try:
            if notify.send_report(analyses):
                print("TG    sent")
            else:
                print("TG    not configured -- run scripts/setup_telegram.py")
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
