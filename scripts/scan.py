#!/usr/bin/env python
"""Ranked structure scan for one or more underlyings.

    python scripts/scan.py                          # GLD + QQQ, 0-45 DTE
    python scripts/scan.py --symbols QQQ --dte 0 10 # short-dated only
    python scripts/scan.py --top 20 --json out/scan.json

Prints regime context first, then the candidates that survive crossing the
market. An empty table is a normal and useful result.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optionsdesk.scanner import scan_symbol  # noqa: E402

COLS = ["expiry", "dte", "name", "cost", "slippage", "ev_empirical",
        "edge", "edge_per_risk", "pop_empirical", "max_loss", "verdict"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="GLD,QQQ")
    ap.add_argument("--source", default="auto", choices=["auto", "ibkr", "marketdata", "yahoo"])
    ap.add_argument("--dte", nargs=2, type=float, default=[0, 45], metavar=("MIN", "MAX"))
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--aggressive", action="store_true",
                    help="include undefined-risk structures (still unranked)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    pd.set_option("display.width", 220)
    payload = {}

    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        try:
            r = scan_symbol(sym, source=args.source, dte_range=tuple(args.dte),
                            aggressive=args.aggressive)
        except Exception as exc:
            print(f"[{sym}] FAILED: {exc}", file=sys.stderr)
            continue

        g = r["regime"]
        print("=" * 100)
        print(f"  {r['symbol']}  {r['spot']:.2f}   [{r['source']}]   {r['n_fitted']} expiries fitted")
        print("=" * 100)
        flip = g["flip_level"]
        print(f"  gamma        {g['gamma_regime']}   net GEX ${g['net_gex']:,.0f} per 1%")
        if flip == flip:
            print(f"  flip level   {flip:,.2f}   spot {g['spot_vs_flip_pct']:+.2f}% away")
        if g["iv30"] and g["rv20"] == g["rv20"]:
            print(f"  IV30/RV20    {g['iv30']*100:.1f}% / {g['rv20']*100:.1f}%   "
                  f"VRP {g['vrp']*100:+.1f} pts"
                  f"{'   <-- realized ABOVE implied, premium selling underpaid' if g['vrp'] < 0 else ''}")
        for w in r.get("warnings", []):
            print(f"  ! {w}")

        c = r["candidates"]
        if c is None or c.empty:
            print("\n  no candidate survived the cost filter -- nothing worth doing here\n")
        else:
            pos = int((c["edge"] > 0).sum())
            tradeable = int((c["ev_empirical"] > 0).sum())
            print(f"\n  {len(c)} candidates priced | {pos} beat the market's own pricing | "
                  f"{tradeable} with genuinely POSITIVE expectancy after costs\n")
            if tradeable == 0:
                print("  none of these makes money on average once you cross the spread.\n")
            print(c[COLS].head(args.top).to_string(index=False,
                                                   float_format=lambda x: f"{x:,.2f}"))
            print()

        rv = r.get("relative_value")
        if rv is not None and len(rv):
            print(f"  {len(rv)} single contracts off their smile and past costs:")
            print(rv[["expiry", "right", "strike", "residual_vol", "net_edge", "action"]]
                  .head(5).to_string(index=False))
            print()

        payload[r["symbol"]] = {
            "spot": r["spot"], "asof": r["asof"], "source": r["source"],
            "regime": g,
            "candidates": (c[COLS].head(args.top).to_dict("records")
                           if c is not None and not c.empty else []),
        }

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
        print(f"JSON  {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
