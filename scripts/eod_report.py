#!/usr/bin/env python
"""End-of-day scorecard: mark every tracked daily/weekly position to the
closing price and report which currently sit in profit vs loss.

    python scripts/eod_report.py --telegram
    python scripts/eod_report.py --symbols GLD,QQQ,IBIT,SOXL --source auto

This is a track record, not a status feed: format_desk_status_he (used by the
morning report and watch.py) tells you what to DO right now; this tells you
how the desk's own past picks actually DID, once the closing print settles.
Run it once, near the close -- not on the ten-minute watch cadence.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optionsdesk.deskrun import symbol_status  # noqa: E402
from optionsdesk.ledger import Ledger  # noqa: E402
from optionsdesk.scanner import scan_symbol  # noqa: E402

DEFAULT_SYMBOLS = ["GLD", "QQQ", "IBIT", "SOXL"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--source", default="auto",
                    choices=["auto", "ibkr", "yahoo", "marketdata"])
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    today = _dt.date.today()
    ledger = Ledger()
    desk_status = {}

    for sym in symbols:
        try:
            # dte_range mirrors watch.py's cost note: the daily/weekly buckets
            # never need anything past this week's Friday, and a scheduled EOD
            # run pays real credits on a metered source for every expiry pulled.
            scan = scan_symbol(sym, source=args.source, dte_range=(0, 9), max_expiries=4)
            desk_status[sym] = symbol_status(sym, scan, ledger, today=today)
            print(f"[{sym}] marked to close")
        except Exception as exc:
            print(f"[{sym}] FAILED: {exc}", file=sys.stderr)

    if not desk_status:
        print("no symbol produced a status -- nothing to report", file=sys.stderr)
        return 1

    from optionsdesk import notify
    text = notify.format_eod_digest_he(desk_status, today)
    print(text)

    if args.telegram:
        cfg = notify.load_config()
        if cfg is None:
            print("TG    not configured -- run scripts/setup_telegram.py")
        else:
            ok = notify.send(text, cfg)
            print("TG    sent" if ok else "TG    failed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
