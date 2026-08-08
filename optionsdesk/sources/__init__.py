"""Data-source factory with automatic fallback.

Policy: try IBKR first (real-time, correct OI), fall back to Yahoo when TWS is
not reachable. That is what makes the same code path work both on the desk --
Gateway running, live data -- and in a scheduled cloud run where localhost has
no Gateway at all.
"""

from __future__ import annotations

from .base import CHAIN_COLUMNS, ChainSnapshot, ChainSource
from .ibkr import IBKRSource
from .yahoo import YahooSource

__all__ = [
    "CHAIN_COLUMNS", "ChainSnapshot", "ChainSource",
    "IBKRSource", "YahooSource", "get_source", "fetch",
]

_SOURCES = {"ibkr": IBKRSource, "yahoo": YahooSource}


def get_source(name: str) -> ChainSource:
    try:
        return _SOURCES[name.lower()]()
    except KeyError:
        raise ValueError(
            f"unknown source {name!r}; expected one of {sorted(_SOURCES)}"
        ) from None


def fetch(symbol: str, source: str = "auto", max_expiries: int = 8) -> ChainSnapshot:
    """Pull one snapshot.

    source='auto'  try IBKR, silently fall back to Yahoo (records a warning)
    source='ibkr'  fail loudly if TWS/Gateway is unreachable
    source='yahoo' skip IBKR entirely
    """
    source = (source or "auto").lower()

    if source in ("ibkr", "auto"):
        try:
            return IBKRSource().fetch(symbol, max_expiries=max_expiries)
        except Exception as exc:
            if source == "ibkr":
                raise
            snap = YahooSource().fetch(symbol, max_expiries=max_expiries)
            snap.warnings.insert(
                0, f"IBKR unavailable ({_short(exc)}); fell back to delayed Yahoo data"
            )
            return snap

    return YahooSource().fetch(symbol, max_expiries=max_expiries)


def _short(exc: Exception, limit: int = 140) -> str:
    msg = " ".join(str(exc).split())
    return msg if len(msg) <= limit else msg[: limit - 1] + "…"
