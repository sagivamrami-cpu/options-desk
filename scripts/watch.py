#!/usr/bin/env python
"""Continuous watcher: scan, compare with the last pass, alert only on change.

    python scripts/watch.py                       # one pass, GLD + QQQ
    python scripts/watch.py --market-hours-only   # no-op outside RTH
    python scripts/watch.py --notify              # macOS notification on alerts
    python scripts/watch.py --quiet               # print only when something fires
    python scripts/watch.py --no-positions        # regime alerts only, skip the ledger

Each pass appends a row to `data/live/intraday-YYYY-MM-DD.csv` and, when a rule
fires, writes `data/live/alerts-YYYY-MM-DD.jsonl`. The design point is that
nothing wakes a human or a language model unless the state actually changed --
see optionsdesk/alerts.py and optionsdesk/deskrun.py for why every rule keys
off a crossing rather than a level.

COST NOTE FOR METERED SOURCES (marketdata.app)
------------------------------------------------
An options chain costs roughly one credit per contract returned, not one per
request. Building this project's daily/weekly tracking spent the entire
10,000-credit free-tier day just from development testing. Two defaults here
exist specifically to keep a SCHEDULED run affordable:

  * --dte defaults to [0, 9], not [0, 45]. The daily and weekly buckets never
    need anything past this week's Friday; a wide 45-day scan every ten
    minutes is paying for information this script never uses.
  * --expiries defaults to 4, capping how many of those near dates get pulled.

Even tightened, running this every 10 minutes on marketdata.app all session
is still tens of thousands of credits a day -- outside the free tier. Point
--source at yahoo for frequent polling (free, and open interest does not
change intraday, so its only real weakness -- pre-market zeros -- does not
apply once the session is running) and reserve marketdata for the once-a-day
full report, or lengthen --interval, or upgrade the plan.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import subprocess
import sys
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from optionsdesk import alerts as A  # noqa: E402
from optionsdesk.deskrun import ledger_alerts, symbol_status  # noqa: E402
from optionsdesk.ledger import Ledger  # noqa: E402
from optionsdesk.scanner import scan_symbol  # noqa: E402

LIVE = ROOT / "data" / "live"
NY = zoneinfo.ZoneInfo("America/New_York")

FIELDS = ["ts_utc", "ts_ny", "symbol", "source", "spot", "regime", "net_gex",
          "flip_level", "spot_vs_flip_pct", "iv30", "rv20", "vrp",
          "n_candidates", "n_positive_ev", "best_ev", "n_alerts"]


def in_market_hours(now_ny) -> bool:
    if now_ny.weekday() >= 5:
        return False
    return _dt.time(9, 30) <= now_ny.time() <= _dt.time(16, 0)


def last_row(path: Path, symbol: str):
    if not path.exists():
        return None
    try:
        d = pd.read_csv(path)
    except Exception:
        return None
    d = d[d["symbol"] == symbol]
    return None if d.empty else d.iloc[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="GLD,QQQ")
    ap.add_argument("--source", default="auto",
                    choices=["auto", "ibkr", "yahoo", "marketdata"])
    ap.add_argument("--dte", nargs=2, type=float, default=[0, 9],
                    help="default covers the daily+weekly buckets only; see the cost note above")
    ap.add_argument("--expiries", type=int, default=4)
    ap.add_argument("--market-hours-only", action="store_true")
    ap.add_argument("--notify", action="store_true", help="macOS notification on alert")
    ap.add_argument("--telegram", action="store_true", help="push alerts to Telegram")
    ap.add_argument("--lang", default="he", choices=["he", "en"],
                    help="alert language on Telegram (default Hebrew)")
    ap.add_argument("--quiet", action="store_true", help="print only when a rule fires")
    ap.add_argument("--positions", action="store_true", default=True,
                    help="track daily/weekly recommendations against the ledger")
    ap.add_argument("--no-positions", dest="positions", action="store_false")
    args = ap.parse_args()

    now_ny = _dt.datetime.now(NY)
    if args.market_hours_only and not in_market_hours(now_ny):
        if not args.quiet:
            print(f"[watch] {now_ny:%Y-%m-%d %H:%M} ET outside RTH, skipping")
        return 0

    LIVE.mkdir(parents=True, exist_ok=True)
    day = now_ny.date().isoformat()
    csv_path = LIVE / f"intraday-{day}.csv"
    alert_path = LIVE / f"alerts-{day}.jsonl"

    ledger = Ledger() if args.positions else None
    desk_status: dict = {}

    fired: list[A.Alert] = []
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        try:
            scan = scan_symbol(sym, source=args.source, dte_range=tuple(args.dte),
                               max_expiries=args.expiries)
        except Exception as exc:
            fired.append(A.Alert("critical", sym, "scan_failed", str(exc), {}))
            continue

        prev = last_row(csv_path, sym)
        found = A.evaluate(scan, prev)
        fired.extend(found)

        # Mark-to-market and, if a bucket is empty, pick a fresh daily/weekly
        # candidate -- reusing this SAME scan, so tracking positions never
        # costs a second fetch on top of the regime check above.
        if ledger is not None:
            try:
                desk_status[sym] = symbol_status(sym, scan, ledger, today=now_ny.date())
            except Exception as exc:
                print(f"[watch] {sym} position tracking failed: {exc}", file=sys.stderr)

        reg = scan.get("regime", {})
        c = scan.get("candidates")
        pos = c[c["ev_empirical"] > 0] if c is not None and len(c) else None
        now = _dt.datetime.now(_dt.timezone.utc)

        row = {
            "ts_utc": now.isoformat(timespec="seconds"),
            "ts_ny": now.astimezone(NY).isoformat(timespec="seconds"),
            "symbol": scan["symbol"], "source": scan["source"],
            "spot": round(scan["spot"], 4),
            "regime": reg.get("gamma_regime"),
            "net_gex": round(reg.get("net_gex", float("nan")), 0),
            "flip_level": round(reg.get("flip_level", float("nan")), 4),
            "spot_vs_flip_pct": round(reg.get("spot_vs_flip_pct", float("nan")), 3),
            "iv30": round(reg.get("iv30") or float("nan"), 5),
            "rv20": round(reg.get("rv20", float("nan")), 5),
            "vrp": round(reg.get("vrp", float("nan")), 5),
            "n_candidates": 0 if c is None else int(len(c)),
            "n_positive_ev": 0 if pos is None else int(len(pos)),
            "best_ev": round(float(pos["ev_empirical"].max()), 2) if pos is not None and len(pos) else "",
            "n_alerts": len(found),
        }
        write_header = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if write_header:
                w.writeheader()
            w.writerow(row)

        if not args.quiet:
            print(f"[watch] {sym:5s} {scan['spot']:>9.2f}  {reg.get('gamma_regime','?'):12s} "
                  f"flip {reg.get('flip_level', float('nan')):>9.2f} "
                  f"({reg.get('spot_vs_flip_pct', float('nan')):+.2f}%)  "
                  f"VRP {reg.get('vrp', float('nan'))*100:+.1f}  "
                  f"cand {row['n_candidates']}/{row['n_positive_ev']}+  "
                  f"alerts {len(found)}")

    if desk_status:
        pos_alerts = ledger_alerts(desk_status)
        fired.extend(pos_alerts)
        if not args.quiet and pos_alerts:
            print(f"[watch] {len(pos_alerts)} position event(s): "
                  + ", ".join(f"{a.symbol}/{a.kind}" for a in pos_alerts))

    if fired:
        with alert_path.open("a", encoding="utf-8") as fh:
            stamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            for a in fired:
                fh.write(json.dumps({"ts": stamp, **a.to_dict()}) + "\n")

        digest = A.format_digest(fired)
        print("\n" + "=" * 78)
        print(f"  {len(fired)} ALERT(S)  {now_ny:%H:%M ET}")
        print("=" * 78)
        print(digest)
        print()

        if args.telegram:
            from optionsdesk import notify
            sender = notify.send_alerts_he if args.lang == "he" else notify.send_alerts
            try:
                sender(fired)
            except Exception as exc:
                print(f"[watch] telegram failed: {exc}", file=sys.stderr)

        if args.notify and sys.platform == "darwin":
            top = fired[0]
            subprocess.run([
                "osascript", "-e",
                f'display notification "{top.message[:180]}" '
                f'with title "options-desk: {top.symbol}" subtitle "{top.kind}"',
            ], capture_output=True)
    elif not args.quiet:
        print("[watch] nothing changed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
