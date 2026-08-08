"""Yahoo Finance adapter (yfinance).

Free, unauthenticated, ~15 minutes delayed. Good enough for positioning work:
open interest only updates once per day anyway, so the metrics that matter most
here -- GEX, max pain, OI walls -- are not sensitive to intraday delay.

Known quirks handled below:
  * Yahoo's own `impliedVolatility` is unreliable on illiquid strikes and can
    come back as a flat 1e-5 or 2.0. We keep it only when it looks sane and let
    the metrics layer re-solve the rest from mid prices.
  * `openInterest` is sometimes missing entirely on freshly listed expiries.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from .base import ChainSnapshot, ChainSource

# Outside this band Yahoo's IV field is noise rather than a quote.
_IV_SANE = (0.01, 3.0)


class YahooSource(ChainSource):
    name = "yahoo"

    def fetch(self, symbol: str, max_expiries: int = 8) -> ChainSnapshot:
        import yfinance as yf

        warnings: list[str] = []
        tkr = yf.Ticker(symbol)

        hist = tkr.history(period="1y", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            raise RuntimeError(f"yahoo: no price history for {symbol}")
        history = pd.DataFrame({"close": hist["Close"].astype(float)})
        history.index = pd.to_datetime(history.index).tz_localize(None)

        spot = float(history["close"].iloc[-1])
        # Prefer a live quote when the market is open; fall back to last close.
        try:
            fast = tkr.fast_info
            live = float(fast["last_price"])
            if live > 0:
                spot = live
        except Exception:
            warnings.append("yahoo: live quote unavailable, using last daily close")

        try:
            all_exp = list(tkr.options)
        except Exception as exc:
            raise RuntimeError(f"yahoo: could not list expiries for {symbol}: {exc}") from exc
        if not all_exp:
            raise RuntimeError(f"yahoo: {symbol} has no listed options")

        frames = []
        for exp in all_exp[:max_expiries]:
            try:
                oc = tkr.option_chain(exp)
            except Exception as exc:
                warnings.append(f"yahoo: skipped expiry {exp} ({exc})")
                continue
            for right, raw in (("C", oc.calls), ("P", oc.puts)):
                if raw is None or raw.empty:
                    continue
                frames.append(pd.DataFrame({
                    "expiry": exp,
                    "right": right,
                    "strike": raw["strike"],
                    "bid": raw.get("bid"),
                    "ask": raw.get("ask"),
                    "last": raw.get("lastPrice"),
                    "volume": raw.get("volume"),
                    "open_interest": raw.get("openInterest"),
                    "iv": raw.get("impliedVolatility"),
                }))

        if not frames:
            raise RuntimeError(f"yahoo: no option data returned for {symbol}")

        df = pd.concat(frames, ignore_index=True)
        bad_iv = ~df["iv"].between(*_IV_SANE)
        if bad_iv.any():
            warnings.append(
                f"yahoo: discarded {int(bad_iv.sum())} implausible IV quotes, re-solving from mids"
            )
            df.loc[bad_iv, "iv"] = float("nan")

        asof = _dt.datetime.now()
        return ChainSnapshot(
            symbol=symbol.upper(),
            spot=spot,
            chain=self._finalise(df, asof),
            asof=asof,
            source=self.name,
            history=history,
            warnings=warnings,
        )
