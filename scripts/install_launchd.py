#!/usr/bin/env python
"""Install (or remove) the macOS launchd agents for this project.

Two independent jobs:

  daily    generates the full report once a day at a fixed local time.
           Needs nothing but an internet connection -- works today, on Yahoo
           data, with no broker account.

  collect  appends an intraday positioning row every N minutes during RTH.
           Only worth running once IB Gateway is up; on Yahoo it just re-reads
           the same once-a-day open interest.

    python scripts/install_launchd.py --job daily --at 15:30
    python scripts/install_launchd.py --job daily --at 15:30 --open
    python scripts/install_launchd.py --job collect --interval 300 --push
    python scripts/install_launchd.py --status
    python scripts/install_launchd.py --job daily --uninstall

Times for `--at` are your Mac's LOCAL time, not UTC and not exchange time.
US pre-market 08:30 ET is 15:30 in Israel during summer, 15:30 -> 16:30 when
US daylight time ends in November. launchd has no timezone awareness, so
re-run with a new --at if you want to track the exchange rather than the clock.
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
LOG_DIR = ROOT / "data" / "logs"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"

LABELS = {
    "daily": "com.optionsdesk.daily",
    "collect": "com.optionsdesk.collect",
    "watch": "com.optionsdesk.watch",
}

# launchd hands jobs a minimal PATH; git and open need a real one.
_ENV = {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"}


def plist_path(job: str) -> Path:
    return LAUNCH_AGENTS / f"{LABELS[job]}.plist"


def build_daily(args) -> dict:
    hh, mm = _parse_at(args.at)
    cmd = [str(PYTHON), str(ROOT / "scripts" / "daily_report.py"),
           "--symbols", args.symbols, "--source", args.source]
    if args.open:
        # Chain the open so the report surfaces instead of sitting in out/.
        script = (f'{_q(cmd)} && open "$(ls -t {ROOT}/out/report-*.html | head -1)"')
        program = ["/bin/sh", "-lc", script]
    else:
        program = cmd
    return {
        "Label": LABELS["daily"],
        "ProgramArguments": program,
        # Mon-Fri only: a weekend run just re-reads Friday's chain.
        "StartCalendarInterval": [
            {"Weekday": d, "Hour": hh, "Minute": mm} for d in range(1, 6)
        ],
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / "daily.log"),
        "StandardErrorPath": str(LOG_DIR / "daily.err.log"),
        "RunAtLoad": False,
        "EnvironmentVariables": _ENV,
    }


def build_watch(args) -> dict:
    """Continuous scan that alerts only when the state changes."""
    cmd = [str(PYTHON), str(ROOT / "scripts" / "watch.py"),
           "--symbols", args.symbols, "--source", args.source,
           "--market-hours-only", "--quiet"]
    if args.notify:
        cmd.append("--notify")
    return {
        "Label": LABELS["watch"],
        "ProgramArguments": cmd,
        "StartInterval": args.interval,
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / "watch.log"),
        "StandardErrorPath": str(LOG_DIR / "watch.err.log"),
        "RunAtLoad": False,
        "EnvironmentVariables": _ENV,
    }


def build_collect(args) -> dict:
    cmd = [str(PYTHON), str(ROOT / "scripts" / "collect.py"),
           "--symbols", args.symbols, "--source", args.source,
           "--market-hours-only"]
    if args.push:
        cmd.append("--push")
    return {
        "Label": LABELS["collect"],
        "ProgramArguments": cmd,
        "StartInterval": args.interval,
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / "collect.log"),
        "StandardErrorPath": str(LOG_DIR / "collect.err.log"),
        "RunAtLoad": False,
        "EnvironmentVariables": _ENV,
    }


def _parse_at(s: str):
    try:
        hh, mm = s.split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
        return hh, mm
    except ValueError:
        sys.exit(f"--at must look like HH:MM in 24-hour local time, got {s!r}")


def _q(cmd):
    return " ".join(f'"{c}"' for c in cmd)


def install(args):
    if not PYTHON.exists():
        sys.exit(f"venv python not found at {PYTHON} -- create it first")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    spec = {"daily": build_daily, "watch": build_watch,
            "collect": build_collect}[args.job](args)
    path = plist_path(args.job)
    path.write_bytes(plistlib.dumps(spec))

    _launchctl("bootout", f"gui/{_uid()}/{LABELS[args.job]}")     # ignore if absent
    r = _launchctl("bootstrap", f"gui/{_uid()}", str(path))
    if r.returncode != 0:
        sys.exit(f"launchctl bootstrap failed: {r.stderr.strip()}")

    print(f"installed {LABELS[args.job]}")
    print(f"  plist   {path}")
    if args.job == "daily":
        print(f"  runs    weekdays at {args.at} local, {args.symbols} via {args.source}")
        print(f"  opens   {'yes' if args.open else 'no'}")
        print(f"  logs    {LOG_DIR / 'daily.log'}")
    elif args.job == "watch":
        every = f"{args.interval}s" if args.interval < 60 else f"{args.interval // 60} min"
        print(f"  runs    every {every}, RTH only, {args.symbols} via {args.source}")
        print(f"  alerts  only on state change; notify {'on' if args.notify else 'off'}")
        print(f"  logs    {LOG_DIR / 'watch.log'}")
    else:
        every = f"{args.interval}s" if args.interval < 60 else f"{args.interval // 60} min"
        print(f"  runs    every {every}, RTH only, {args.symbols} via {args.source}")
        print(f"  push    {'on' if args.push else 'off'}")
        print(f"  logs    {LOG_DIR / 'collect.log'}")
    print("\ncheck with:  python scripts/install_launchd.py --status")


def uninstall(args):
    _launchctl("bootout", f"gui/{_uid()}/{LABELS[args.job]}")
    p = plist_path(args.job)
    if p.exists():
        p.unlink()
    print(f"removed {LABELS[args.job]}")


def status(_):
    for job, label in LABELS.items():
        r = _launchctl("print", f"gui/{_uid()}/{label}")
        if r.returncode != 0:
            print(f"{job:8s} NOT loaded")
            continue
        state = next((l.strip() for l in r.stdout.splitlines() if "state =" in l), "")
        exit_ = next((l.strip() for l in r.stdout.splitlines() if "last exit code" in l), "")
        print(f"{job:8s} loaded   {state}   {exit_}")
    for name in ("daily.log", "watch.log", "collect.log"):
        log = LOG_DIR / name
        if log.exists():
            tail = log.read_text(encoding="utf-8").splitlines()[-5:]
            if tail:
                print(f"\n--- {name} ---")
                print("\n".join(tail))


def _launchctl(*a):
    return subprocess.run(["launchctl", *a], capture_output=True, text=True)


def _uid():
    return subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", choices=["daily", "watch", "collect"], default="daily")
    ap.add_argument("--at", default="15:30", help="daily: local HH:MM (default 15:30)")
    ap.add_argument("--open", action="store_true", help="daily: open the report when done")
    ap.add_argument("--interval", type=int, default=300, help="collect: seconds between runs")
    ap.add_argument("--symbols", default="GLD,QQQ")
    ap.add_argument("--source", default="auto", choices=["auto", "ibkr", "yahoo"])
    ap.add_argument("--push", action="store_true", help="collect: git push each run")
    ap.add_argument("--notify", action="store_true", help="watch: macOS notification on alert")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        return status(args)
    if args.uninstall:
        return uninstall(args)
    return install(args)


if __name__ == "__main__":
    main()
