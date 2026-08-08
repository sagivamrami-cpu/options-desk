#!/usr/bin/env python
"""Continuous intraday collector.

Runs one snapshot per invocation and appends a compact row per symbol to a
rolling intraday CSV. Scheduled every N minutes by launchd, this builds a
time series of how dealer positioning MOVES during the session -- which is
information a once-a-day report cannot give you.

    python scripts/collect.py                       # one pass, GLD + QQQ
    python scripts/collect.py --symbols QQQ         # one symbol
    python scripts/collect.py --market-hours-only   # no-op outside RTH
    python scripts/collect.py --push                # git commit + push after

Why a rolling CSV rather than full chain dumps: a full chain is ~60 KB of JSON
per symbol per pull. At 5-minute intervals that is 500 MB a year for nothing --
the chain is only useful at the moment it is read. What has lasting value is the
derived series: GEX, flip level, IV, skew, VRP. Those are 12 numbers a row.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import subprocess
import sys
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optionsdesk.report import analyze  # noqa: E402

LIVE_DIR = ROOT / "data" / "live"
NY = zoneinfo.ZoneInfo("America/New_York")

FIELDS = [
    "ts_utc", "ts_ny", "symbol", "source", "spot",
    "gex_total", "flip_level", "spot_vs_flip_pct", "regime",
    "iv30", "rv20", "vrp", "skew_front", "term_slope", "inverted",
    "vanna", "charm", "pcr_oi", "front_expiry", "front_max_pain", "tilt",
]


def in_market_hours(now_ny: _dt.datetime) -> bool:
    """US regular trading hours, Mon-Fri 09:30-16:00 ET.

    Deliberately ignores exchange holidays: a holiday pull simply returns
    yesterday's stale chain, which is harmless, and hardcoding a holiday
    calendar here would rot silently.
    """
    if now_ny.weekday() >= 5:
        return False
    open_, close = _dt.time(9, 30), _dt.time(16, 0)
    return open_ <= now_ny.time() <= close


def collect_one(symbol: str, source: str, expiries: int) -> dict:
    a = analyze(symbol, source=source, max_expiries=expiries, persist=False)
    now = _dt.datetime.now(_dt.timezone.utc)
    front = a["expiries"][0] if a["expiries"] else {}
    return {
        "ts_utc": now.isoformat(timespec="seconds"),
        "ts_ny": now.astimezone(NY).isoformat(timespec="seconds"),
        "symbol": a["symbol"],
        "source": a["source"],
        "spot": _r(a["spot"], 4),
        "gex_total": _r(a["gex"]["total"], 0),
        "flip_level": _r(a["gex"]["flip_level"], 4),
        "spot_vs_flip_pct": _r(a["gex"]["spot_vs_flip_pct"], 3),
        "regime": a["gex"]["regime"],
        "iv30": _r(a["vol"]["iv30"], 5),
        "rv20": _r(a["vol"]["rv20"], 5),
        "vrp": _r(a["vol"]["vrp"]["vrp"], 5),
        "skew_front": _r(a["skew"]["front"]["skew"], 5),
        "term_slope": _r(a["vol"]["term_slope"], 5),
        "inverted": a["vol"]["inverted"],
        "vanna": _r(a["flows"]["vanna"], 0),
        "charm": _r(a["flows"]["charm"], 0),
        "pcr_oi": _r(a["flows"]["put_call"]["oi_ratio"], 4),
        "front_expiry": front.get("expiry", ""),
        "front_max_pain": _r(front.get("max_pain"), 2),
        "tilt": a["read"]["tilt"],
    }


def _r(v, nd):
    try:
        f = float(v)
        return "" if f != f else round(f, nd)   # NaN -> empty cell
    except (TypeError, ValueError):
        return ""


def append(row: dict) -> Path:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    day = _dt.datetime.fromisoformat(row["ts_ny"]).date().isoformat()
    path = LIVE_DIR / f"intraday-{day}.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return path


def git_push(paths: list[Path]) -> None:
    """Publish the collected rows so a cloud agent can read them.

    This is the ONLY bridge between local IBKR data and anything running off
    this machine. The API is localhost-only; a scheduled cloud run cannot dial
    into your Gateway. Pushing the derived series to a private repo is what
    makes live IBKR numbers reachable from elsewhere.
    """
    try:
        subprocess.run(["git", "add", *[str(p) for p in paths]],
                       cwd=ROOT, check=True, capture_output=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if r.returncode == 0:
            print("[collect] nothing new to push")
            return
        stamp = _dt.datetime.now(NY).strftime("%Y-%m-%d %H:%M ET")
        subprocess.run(["git", "commit", "-m", f"data: intraday snapshot {stamp}"],
                       cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True, capture_output=True)
        print("[collect] pushed")
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode().strip()
        print(f"[collect] git push failed: {err or exc}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="GLD,QQQ")
    ap.add_argument("--source", default="auto", choices=["auto", "ibkr", "yahoo"])
    ap.add_argument("--expiries", type=int, default=6)
    ap.add_argument("--market-hours-only", action="store_true")
    ap.add_argument("--push", action="store_true", help="git commit + push after collecting")
    args = ap.parse_args()

    now_ny = _dt.datetime.now(NY)
    if args.market_hours_only and not in_market_hours(now_ny):
        print(f"[collect] {now_ny:%Y-%m-%d %H:%M} ET is outside RTH, skipping")
        return 0

    written, failed = [], 0
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        try:
            row = collect_one(sym, args.source, args.expiries)
            path = append(row)
            written.append(path)
            print(f"[collect] {sym:5s} {row['spot']:>10}  GEX {row['gex_total']:>16,}  "
                  f"flip {row['flip_level']:>10}  [{row['source']}]")
        except Exception as exc:
            failed += 1
            print(f"[collect] {sym}: FAILED {exc}", file=sys.stderr)

    if args.push and written:
        git_push(sorted(set(written)))

    return 1 if written == [] and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
