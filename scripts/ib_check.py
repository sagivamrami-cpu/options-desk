#!/usr/bin/env python
"""Diagnose the Interactive Brokers connection, one layer at a time.

Run this BEFORE trying to use --source ibkr. It isolates exactly which of the
five things that can be wrong is actually wrong, instead of leaving you with a
generic timeout.

    python scripts/ib_check.py
    python scripts/ib_check.py --symbol GLD

Layers tested, in order:
  1. TCP    is anything listening on the API ports at all
  2. API    does the handshake succeed (API enabled? client ID free?)
  3. QUOTE  do we get a live underlying price (market-data entitlement)
  4. CHAIN  does reqSecDefOptParams return expirations and strikes
  5. OPRA   does a real option contract return bid/ask, IV and OPEN INTEREST
            -- this is the layer that decides whether GEX and max pain work
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import socket
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from optionsdesk.sources.ibkr import DEFAULT_PORTS, _MDT_NAMES  # noqa: E402

OK, WARN, BAD = "  OK  ", " WARN ", " FAIL "


def _p(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def check_tcp(host, ports):
    _p("....", f"probing {host} on ports {list(ports)} …")
    live = []
    for port in ports:
        s = socket.socket()
        s.settimeout(1.5)
        try:
            s.connect((host, port))
            live.append(port)
            _p(OK, f"port {port} is open ({_port_label(port)})")
        except Exception:
            pass
        finally:
            s.close()
    if not live:
        _p(BAD, "nothing is listening on any API port.")
        print("""
      Fix: start TWS or IB Gateway and log in, then enable the API:
        TWS      File > Global Configuration > API > Settings
        Gateway  Configure > Settings > API > Settings
      Tick "Enable ActiveX and Socket Clients".
      Add 127.0.0.1 under "Trusted IPs".
""")
    return live


def _port_label(port):
    return {7496: "TWS live", 7497: "TWS paper",
            4001: "Gateway live", 4002: "Gateway paper"}.get(port, "unknown")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--symbol", default="QQQ")
    ap.add_argument("--client-id", type=int, default=99)
    args = ap.parse_args()

    print("=" * 66)
    print("  IBKR CONNECTION DIAGNOSTIC")
    print("=" * 66)

    live_ports = check_tcp(args.host, DEFAULT_PORTS)
    if not live_ports:
        return 1

    from ib_insync import IB, Option, Stock

    ib = IB()
    port = live_ports[0]
    try:
        ib.connect(args.host, port, clientId=args.client_id, timeout=12, readonly=True)
    except Exception as exc:
        _p(BAD, f"API handshake failed on port {port}: {exc}")
        print("""
      Common causes:
        * "Enable ActiveX and Socket Clients" is off
        * that client ID is already in use -- try --client-id 123
        * a "Accept incoming connection?" popup is waiting in TWS
""")
        return 1

    _p(OK, f"connected to {_port_label(port)} on port {port}, "
           f"server v{ib.client.serverVersion()}")
    accounts = ib.managedAccounts()
    _p(OK, f"accounts visible: {', '.join(accounts) or '(none)'}")
    paper = any(a.startswith("D") for a in accounts)
    _p(OK if not paper else WARN,
       f"account type: {'PAPER' if paper else 'LIVE'}"
       + (" -- paper accounts often have weaker data entitlements" if paper else ""))

    try:
        # -------- layer 3: underlying quote --------------------------
        stk = Stock(args.symbol.upper(), "SMART", "USD")
        (stk,) = ib.qualifyContracts(stk)

        working_mdt = None
        for mdt in (1, 3, 4):
            ib.reqMarketDataType(mdt)
            t = ib.reqMktData(stk, "", False, False)
            ib.sleep(2.5)
            px = t.marketPrice()
            ib.cancelMktData(stk)
            if px is not None and math.isfinite(px) and px > 0:
                working_mdt = mdt
                _p(OK if mdt == 1 else WARN,
                   f"{args.symbol} quote {px:.2f} via {_MDT_NAMES[mdt]} data")
                break
        if working_mdt is None:
            _p(BAD, f"no quote for {args.symbol} at any market-data type")
            print("""
      You have no market-data subscription and delayed data is also refused.
      Account Management > Settings > Market Data Subscriptions:
        * "US Securities Snapshot and Futures Value Bundle"  (~$10/mo,
          waived if you pay >$30/mo commissions)
""")
            return 1
        if working_mdt != 1:
            print(f"""
      Working, but on {_MDT_NAMES[working_mdt]} data. Open interest and greeks
      are usually still fine for positioning work. For real-time add:
        * "US Equity and Options Add-On Streaming Bundle" (~$4.50/mo non-pro)
""")

        # -------- layer 4: option chain definition -------------------
        params = ib.reqSecDefOptParams(stk.symbol, "", stk.secType, stk.conId)
        if not params:
            _p(BAD, "reqSecDefOptParams returned nothing -- no option chain visible")
            return 1
        cd = next((p for p in params if p.exchange == "SMART" and p.multiplier == "100"),
                  params[0])
        today = _dt.date.today()
        exps = sorted(e for e in cd.expirations
                      if _dt.datetime.strptime(e, "%Y%m%d").date() >= today)
        _p(OK, f"chain: {len(exps)} future expiries, {len(cd.strikes)} strikes, "
               f"class {cd.tradingClass}")

        # -------- layer 5: a real option contract, incl. OPEN INTEREST
        strike = min(cd.strikes, key=lambda k: abs(k - px))
        opt = Option(stk.symbol, exps[0], strike, "C", "SMART",
                     tradingClass=cd.tradingClass, multiplier="100", currency="USD")
        qual = ib.qualifyContracts(opt)
        if not qual:
            _p(BAD, f"could not qualify {stk.symbol} {exps[0]} {strike} C")
            return 1
        opt = qual[0]

        t = ib.reqMktData(opt, "100,101,106", False, False)
        ib.sleep(5.0)
        bid, ask = t.bid, t.ask
        oi = t.callOpenInterest
        iv = t.modelGreeks.impliedVol if t.modelGreeks else None
        ib.cancelMktData(opt)

        _p(OK if _fin(bid) or _fin(ask) else BAD,
           f"option quote {stk.symbol} {exps[0]} {strike}C -> bid {bid} ask {ask}")
        _p(OK if _fin(iv) else WARN,
           f"model IV: {iv if _fin(iv) else 'not returned (we solve it from mid instead)'}")

        if _fin(oi) and oi > 0:
            _p(OK, f"open interest: {int(oi):,} -- GEX and max pain will be accurate")
        else:
            _p(WARN, "open interest NOT returned")
            print("""
      Everything else works, but without OI the positioning metrics (GEX,
      zero-gamma flip, max pain, OI walls) cannot be computed from IBKR.
      OI ticks require the OPRA options bundle. Until then run:
          python scripts/daily_report.py --source yahoo
      Yahoo gives correct end-of-day OI for free, which is what those
      metrics actually need -- OI only updates once per day anyway.
""")

        print("\n" + "=" * 66)
        print("  READY. Run:  python scripts/daily_report.py --source ibkr")
        print("=" * 66)
        return 0
    finally:
        if ib.isConnected():
            ib.disconnect()


def _fin(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
