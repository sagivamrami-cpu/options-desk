"""Data-source factory with automatic fallback.

Policy: try IBKR first (real-time, correct OI), fall back to Yahoo when TWS is
not reachable. That is what makes the same code path work both on the desk --
Gateway running, live data -- and in a scheduled cloud run where localhost has
no Gateway at all.
"""

from __future__ import annotations

import socket

from .base import CHAIN_COLUMNS, ChainSnapshot, ChainSource
from .ibkr import DEFAULT_PORTS, IBKRSource
from .marketdata import MarketDataSource, load_token
from .yahoo import YahooSource

__all__ = [
    "CHAIN_COLUMNS", "ChainSnapshot", "ChainSource", "DEFAULT_PORTS",
    "IBKRSource", "YahooSource", "MarketDataSource",
    "get_source", "fetch", "gateway_is_up",
]

_SOURCES = {"ibkr": IBKRSource, "yahoo": YahooSource,
            "marketdata": MarketDataSource}


def get_source(name: str) -> ChainSource:
    try:
        return _SOURCES[name.lower()]()
    except KeyError:
        raise ValueError(
            f"unknown source {name!r}; expected one of {sorted(_SOURCES)}"
        ) from None


def gateway_is_up(host: str = "127.0.0.1", ports=None, timeout: float = 0.25) -> bool:
    """Cheap TCP probe for a listening TWS/Gateway.

    Used to keep source='auto' honest. Without this, every run with no Gateway
    pays the cost of ib_insync building a client, opening four sockets and
    unwinding four exceptions before it gives up. A quarter-second probe against
    a closed port returns instantly (connection refused), so 'auto' costs
    effectively nothing when you have no broker connection yet.
    """
    for port in (ports or DEFAULT_PORTS):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            continue
        finally:
            s.close()
    return False


def fetch(symbol: str, source: str = "auto", max_expiries: int = 8) -> ChainSnapshot:
    """Pull one snapshot.

    source='auto'        IBKR if a Gateway is listening, else marketdata.app
                         if a token exists, else Yahoo
    source='ibkr'        fail loudly if TWS/Gateway is unreachable
    source='marketdata'  fail loudly if the token is missing or the call fails
    source='yahoo'       Yahoo only
    """
    source = (source or "auto").lower()

    # Explicit sources must be honoured exactly. An earlier version fell
    # through to Yahoo for anything that was not 'ibkr' or 'auto', so asking
    # for marketdata silently returned Yahoo data labelled as a cross-check --
    # which would have made the two feeds agree by construction and defeated
    # the entire point of having a second one.
    if source == "marketdata":
        return MarketDataSource().fetch(symbol, max_expiries=max_expiries)
    if source == "yahoo":
        return YahooSource().fetch(symbol, max_expiries=max_expiries)

    if source == "auto" and not gateway_is_up():
        # No broker connection configured -- a normal state, not a degraded one.
        # Prefer marketdata.app when a token exists: it is plain REST (so it
        # works from a cloud run) and it carries real open interest, which
        # Yahoo silently zeroes before the open.
        if load_token():
            try:
                return MarketDataSource().fetch(symbol, max_expiries=max_expiries)
            except Exception as exc:
                snap = YahooSource().fetch(symbol, max_expiries=max_expiries)
                snap.warnings.insert(0, f"marketdata unavailable ({_short(exc)}); used Yahoo")
                return snap
        return YahooSource().fetch(symbol, max_expiries=max_expiries)

    if source in ("ibkr", "auto"):
        try:
            return IBKRSource().fetch(symbol, max_expiries=max_expiries)
        except Exception as exc:
            if source == "ibkr":
                raise
            snap = YahooSource().fetch(symbol, max_expiries=max_expiries)
            snap.warnings.insert(
                0, f"IBKR reachable but the pull failed ({_short(exc)}); used Yahoo instead"
            )
            return snap

    return YahooSource().fetch(symbol, max_expiries=max_expiries)


def _short(exc: Exception, limit: int = 140) -> str:
    msg = " ".join(str(exc).split())
    return msg if len(msg) <= limit else msg[: limit - 1] + "…"
