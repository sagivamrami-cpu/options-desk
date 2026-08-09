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
from .yahoo import YahooSource

__all__ = [
    "CHAIN_COLUMNS", "ChainSnapshot", "ChainSource", "DEFAULT_PORTS",
    "IBKRSource", "YahooSource", "get_source", "fetch", "gateway_is_up",
]

_SOURCES = {"ibkr": IBKRSource, "yahoo": YahooSource}


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

    source='auto'  use IBKR only if a Gateway is actually listening, else Yahoo
    source='ibkr'  fail loudly if TWS/Gateway is unreachable
    source='yahoo' skip IBKR entirely
    """
    source = (source or "auto").lower()

    if source == "auto" and not gateway_is_up():
        # No broker connection configured yet -- this is a normal state, not a
        # degraded one, so it does not warrant a warning on every report.
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
