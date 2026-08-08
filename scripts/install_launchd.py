#!/usr/bin/env python
"""Install (or remove) the macOS launchd agent that runs the collector.

    python scripts/install_launchd.py            # every 5 min, RTH only
    python scripts/install_launchd.py --interval 900 --push
    python scripts/install_launchd.py --uninstall
    python scripts/install_launchd.py --status

The agent fires on a fixed interval around the clock and the collector itself
no-ops outside regular trading hours (`--market-hours-only`). That is simpler
and more robust than encoding a trading calendar into the plist, and it means a
half-day or an early close costs you one wasted no-op instead of bad data.

Note this schedules the COLLECTOR, not IB Gateway. Gateway has to be running and
logged in for IBKR data; see docs/IBKR-SETUP.md.
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.optionsdesk.collect"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PYTHON = ROOT / ".venv" / "bin" / "python"
LOG_DIR = ROOT / "data" / "logs"


def build(interval: int, symbols: str, source: str, push: bool) -> dict:
    args = [
        str(PYTHON), str(ROOT / "scripts" / "collect.py"),
        "--symbols", symbols,
        "--source", source,
        "--market-hours-only",
    ]
    if push:
        args.append("--push")
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "StartInterval": interval,
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / "collect.log"),
        "StandardErrorPath": str(LOG_DIR / "collect.err.log"),
        "RunAtLoad": False,
        # launchd hands jobs a minimal PATH; git needs a real one for --push.
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


def _launchctl(*a, check=False):
    return subprocess.run(["launchctl", *a], capture_output=True, text=True, check=check)


def install(args):
    if not PYTHON.exists():
        sys.exit(f"venv python not found at {PYTHON} -- create it first")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    PLIST.write_bytes(plistlib.dumps(build(args.interval, args.symbols,
                                           args.source, args.push)))
    _launchctl("bootout", f"gui/{_uid()}/{LABEL}")          # ignore if absent
    r = _launchctl("bootstrap", f"gui/{_uid()}", str(PLIST))
    if r.returncode != 0:
        sys.exit(f"launchctl bootstrap failed: {r.stderr.strip()}")

    every = f"{args.interval}s" if args.interval < 60 else f"{args.interval // 60} min"
    print(f"installed {LABEL}")
    print(f"  plist    {PLIST}")
    print(f"  runs     every {every}, {args.symbols} via {args.source}, RTH only")
    print(f"  push     {'on' if args.push else 'off'}")
    print(f"  logs     {LOG_DIR / 'collect.log'}")
    print("\nverify with:  python scripts/install_launchd.py --status")


def uninstall(_):
    _launchctl("bootout", f"gui/{_uid()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    print(f"removed {LABEL}")


def status(_):
    r = _launchctl("print", f"gui/{_uid()}/{LABEL}")
    if r.returncode != 0:
        print(f"{LABEL} is NOT loaded")
        return
    for line in r.stdout.splitlines():
        if any(k in line for k in ("state =", "last exit code", "runs =", "path =")):
            print(" ", line.strip())
    log = LOG_DIR / "collect.log"
    if log.exists():
        print(f"\n--- tail {log} ---")
        print("\n".join(log.read_text(encoding="utf-8").splitlines()[-8:]))


def _uid():
    return subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=int, default=300, help="seconds between runs")
    ap.add_argument("--symbols", default="GLD,QQQ")
    ap.add_argument("--source", default="auto", choices=["auto", "ibkr", "yahoo"])
    ap.add_argument("--push", action="store_true", help="git push each collection")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.uninstall:
        return uninstall(args)
    if args.status:
        return status(args)
    return install(args)


if __name__ == "__main__":
    main()
