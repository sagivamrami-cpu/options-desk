"""Interactive Brokers adapter (ib_insync).

Primary source when you are running locally with TWS or IB Gateway up. It gives
real-time NBBO, IB's own model greeks and IV, and correct open interest.

Requirements on the IBKR side, in order of how often they bite:
  1. TWS or IB Gateway must be RUNNING and logged in. There is no cloud path --
     the API is a socket on localhost only.
  2. Configuration > API > Settings > "Enable ActiveX and Socket Clients" on.
  3. The port must match: TWS live 7496, TWS paper 7497,
     Gateway live 4001, Gateway paper 4002. We try all four by default.
  4. Open interest arrives on a separate tick type than the quote, so we request
     generic ticks 100,101,106 and wait for them explicitly.

Market-data entitlements matter: without an options subscription IB returns
delayed data. We request delayed-frozen as a fallback so the pull still
succeeds rather than hanging on empty tickers.
"""

from __future__ import annotations

import datetime as _dt
import math

import pandas as pd

from .base import ChainSnapshot, ChainSource

DEFAULT_PORTS = (7496, 7497, 4001, 4002)
# Generic tick list: 100 = option volume, 101 = option open interest,
# 106 = option implied volatility.
_GENERIC_TICKS = "100,101,106"

_MDT_NAMES = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed-frozen"}


class IBKRSource(ChainSource):
    name = "ibkr"

    def __init__(self, host: str = "127.0.0.1", ports=DEFAULT_PORTS,
                 client_id: int = 17, timeout: float = 12.0,
                 strike_window: float = 0.25, market_data_type: int = 1):
        self.host = host
        self.ports = tuple(ports)
        self.client_id = client_id
        self.timeout = timeout
        # 1 = live, 2 = frozen, 3 = delayed, 4 = delayed-frozen.
        self.market_data_type = market_data_type
        # Only pull strikes within +/- this fraction of spot. A full GLD chain is
        # thousands of contracts; IB throttles hard above ~100 concurrent tickers
        # and the far wings contribute nothing to GEX anyway.
        self.strike_window = strike_window

    def _market_data_ladder(self):
        """Entitlement fallback order, starting from whatever was requested."""
        ladder = [self.market_data_type]
        for mdt in (1, 3, 4):
            if mdt not in ladder:
                ladder.append(mdt)
        return ladder

    # ------------------------------------------------------------------
    def _connect(self, ib):
        last_err = None
        for port in self.ports:
            try:
                ib.connect(self.host, port, clientId=self.client_id,
                           timeout=self.timeout, readonly=True)
                return port
            except Exception as exc:
                last_err = exc
        raise RuntimeError(
            f"ibkr: could not connect to TWS/Gateway on {self.host} ports {self.ports}. "
            f"Is it running with the API enabled? Last error: {last_err}"
        )

    # ------------------------------------------------------------------
    def fetch(self, symbol: str, max_expiries: int = 8) -> ChainSnapshot:
        from ib_insync import IB, Option, Stock, util

        warnings: list[str] = []
        ib = IB()
        port = self._connect(ib)
        try:
            # Delayed-frozen keeps the pull working outside RTH and without a
            # live options subscription; real-time is used when entitled.
            ib.reqMarketDataType(self.market_data_type)

            underlying = Stock(symbol.upper(), "SMART", "USD")
            (underlying,) = ib.qualifyContracts(underlying)

            bars = ib.reqHistoricalData(
                underlying, endDateTime="", durationStr="1 Y",
                barSizeSetting="1 day", whatToShow="TRADES",
                useRTH=True, formatDate=1,
            )
            if not bars:
                raise RuntimeError(f"ibkr: no historical bars for {symbol}")
            hist = util.df(bars)
            history = pd.DataFrame({"close": hist["close"].astype(float)})
            history.index = pd.to_datetime(hist["date"]).dt.tz_localize(None)

            # Probe entitlements on the underlying before requesting hundreds of
            # option lines. Without an OPRA subscription a real-time request
            # returns empty tickers forever rather than erroring, so we detect
            # that here and step down to delayed (3) then delayed-frozen (4).
            spot = float("nan")
            for mdt in self._market_data_ladder():
                if mdt != self.market_data_type:
                    ib.reqMarketDataType(mdt)
                spot_ticker = ib.reqMktData(underlying, "", False, False)
                ib.sleep(2.5)
                try:
                    spot = _first_finite(
                        spot_ticker.marketPrice(), spot_ticker.last, spot_ticker.close
                    )
                except RuntimeError:
                    spot = float("nan")
                ib.cancelMktData(underlying)
                if math.isfinite(spot):
                    if mdt != self.market_data_type:
                        warnings.append(
                            f"ibkr: no real-time entitlement, using {_MDT_NAMES[mdt]} data"
                        )
                        self.market_data_type = mdt
                    break

            if not math.isfinite(spot):
                spot = float(history["close"].iloc[-1])
                warnings.append(
                    "ibkr: no streaming quote for the underlying; using last daily close as spot"
                )

            params = ib.reqSecDefOptParams(
                underlying.symbol, "", underlying.secType, underlying.conId
            )
            if not params:
                raise RuntimeError(f"ibkr: no option parameters returned for {symbol}")
            # Prefer SMART routing with the standard 100-multiplier class.
            chain_def = next(
                (p for p in params if p.exchange == "SMART" and p.multiplier == "100"),
                params[0],
            )

            today = _dt.date.today()
            expiries = sorted(
                e for e in chain_def.expirations
                if _dt.datetime.strptime(e, "%Y%m%d").date() >= today
            )[:max_expiries]

            lo, hi = spot * (1 - self.strike_window), spot * (1 + self.strike_window)
            strikes = sorted(s for s in chain_def.strikes if lo <= s <= hi)
            if not strikes:
                raise RuntimeError(f"ibkr: no strikes near spot {spot:.2f} for {symbol}")

            contracts = [
                Option(underlying.symbol, exp, strike, right, "SMART",
                       tradingClass=chain_def.tradingClass, multiplier="100", currency="USD")
                for exp in expiries for strike in strikes for right in ("C", "P")
            ]
            contracts = [c for c in ib.qualifyContracts(*contracts) if c.conId]
            if not contracts:
                raise RuntimeError(f"ibkr: no contracts qualified for {symbol}")

            rows = []
            # Batch to stay under IB's concurrent market-data line limit.
            for batch in _chunks(contracts, 90):
                tickers = [ib.reqMktData(c, _GENERIC_TICKS, False, False) for c in batch]
                ib.sleep(4.0)
                for c, t in zip(batch, tickers):
                    greeks = t.modelGreeks
                    rows.append({
                        "expiry": _dt.datetime.strptime(c.lastTradeDateOrContractMonth, "%Y%m%d"),
                        "right": c.right,
                        "strike": float(c.strike),
                        "bid": _clean(t.bid),
                        "ask": _clean(t.ask),
                        "last": _clean(t.last if _finite(t.last) else t.close),
                        "volume": _clean(t.volume),
                        "open_interest": _clean(
                            t.callOpenInterest if c.right == "C" else t.putOpenInterest
                        ),
                        "iv": float(greeks.impliedVol) if greeks and _finite(greeks.impliedVol) else float("nan"),
                    })
                    ib.cancelMktData(c)

            df = pd.DataFrame(rows)
            if df.empty:
                raise RuntimeError(f"ibkr: all tickers came back empty for {symbol}")

            if df["open_interest"].fillna(0).sum() == 0:
                warnings.append(
                    "ibkr: open interest came back empty -- OI ticks need an options "
                    "market-data subscription. GEX and max pain will be unreliable."
                )

            asof = _dt.datetime.now()
            return ChainSnapshot(
                symbol=symbol.upper(),
                spot=float(spot),
                chain=self._finalise(df, asof),
                asof=asof,
                source=f"{self.name}:{port}",
                history=history,
                warnings=warnings,
            )
        finally:
            if ib.isConnected():
                ib.disconnect()


# ----------------------------------------------------------------------
def _finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _clean(x) -> float:
    """IB uses -1 as a sentinel for 'no data' on several tick types."""
    if not _finite(x):
        return float("nan")
    v = float(x)
    return float("nan") if v < 0 else v


def _first_finite(*vals) -> float:
    for v in vals:
        if _finite(v) and float(v) > 0:
            return float(v)
    raise RuntimeError("ibkr: could not determine a spot price")


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
