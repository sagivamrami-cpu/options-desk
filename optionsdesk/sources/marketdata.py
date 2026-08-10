"""marketdata.app adapter — options data without a brokerage account.

Why this exists: the IBKR API is a localhost socket, so it cannot serve a cloud
run, and Yahoo silently returns zeros for open interest before the open. This
is a plain REST source with real open interest, so it works from anywhere and
gives a second opinion when one feed goes wrong.

CREDITS ARE THE REAL CONSTRAINT
-------------------------------
The plan limit is measured in credits, and an option chain request costs
roughly ONE CREDIT PER CONTRACT RETURNED, not one per request. Measured on
live QQQ: a single full expiry cost 399 credits. A naive eight-expiry scan of
two symbols burns over five thousand, which is most of a free day's budget in
one pass.

So this adapter is deliberate about what it asks for:

  * `range=otm` halves the cost (208 credits versus 399 on the same expiry)
    and loses nothing for surface work, which uses OTM quotes only.
  * full chains are requested only when open interest across ALL strikes is
    needed, which is the case for GEX and max pain.
  * every response's credit consumption is read from the rate-limit headers
    and recorded, so the cost is visible rather than discovered at month end.

`fetch()` defaults to the full chain because positioning metrics are the
primary product and they need both sides of every strike. Pass
`otm_only=True` when you only want the volatility surface.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from .base import ChainSnapshot, ChainSource

API = "https://api.marketdata.app/v1"
CONFIG_PATH = Path.home() / ".config" / "options-desk" / ".env"


def load_token() -> str | None:
    tok = os.environ.get("MARKETDATA_TOKEN")
    if tok:
        return tok
    if CONFIG_PATH.exists():
        for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("MARKETDATA_TOKEN="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    return None


class MarketDataSource(ChainSource):
    name = "marketdata"

    def __init__(self, token: str | None = None, timeout: float = 40.0,
                 otm_only: bool = False):
        self.token = token or load_token()
        self.timeout = timeout
        self.otm_only = otm_only
        self.credits_used = 0
        self.credits_remaining: int | None = None

    # ------------------------------------------------------------------
    def _get(self, path: str, **params) -> dict:
        if not self.token:
            raise RuntimeError(
                "no marketdata.app token -- set MARKETDATA_TOKEN in the "
                "environment or in ~/.config/options-desk/.env")
        params["token"] = self.token
        url = f"{API}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                # Record the cost before parsing so it is captured even on a
                # response we end up rejecting.
                consumed = r.headers.get("x-api-ratelimit-consumed")
                remaining = r.headers.get("x-api-ratelimit-remaining")
                if consumed:
                    self.credits_used += int(consumed)
                if remaining:
                    self.credits_remaining = int(remaining)
                body = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            raise RuntimeError(
                f"marketdata {path} failed: {e.code} "
                f"{txt.replace(self.token, '<token>')[:200]}") from None

        status = body.get("s")
        if status == "no_data":
            return {}
        if status != "ok":
            raise RuntimeError(f"marketdata {path}: {body.get('errmsg', status)}")
        return body

    # ------------------------------------------------------------------
    def fetch(self, symbol: str, max_expiries: int = 8) -> ChainSnapshot:
        symbol = symbol.upper()
        warnings: list[str] = []

        # --- daily history for realized vol -----------------------------
        candles = self._get(f"stocks/candles/D/{symbol}", countback=260)
        if not candles.get("c"):
            raise RuntimeError(f"marketdata: no daily candles for {symbol}")
        history = pd.DataFrame(
            {"close": [float(x) for x in candles["c"]]},
            index=pd.to_datetime([_dt.datetime.fromtimestamp(t) for t in candles["t"]]),
        )

        # --- expirations -------------------------------------------------
        exps = self._get(f"options/expirations/{symbol}").get("expirations", [])
        today = _dt.date.today()
        exps = [e for e in exps
                if _dt.datetime.strptime(e, "%Y-%m-%d").date() >= today][:max_expiries]
        if not exps:
            raise RuntimeError(f"marketdata: no future expirations for {symbol}")

        frames, spot = [], None
        for exp in exps:
            kw = {"expiration": exp}
            if self.otm_only:
                kw["range"] = "otm"
            body = self._get(f"options/chain/{symbol}", **kw)
            n = len(body.get("optionSymbol", []))
            if not n:
                warnings.append(f"marketdata: empty chain for {exp}")
                continue
            if spot is None and body.get("underlyingPrice"):
                spot = float(body["underlyingPrice"][0])

            def col(key, default=None):
                v = body.get(key)
                return v if v is not None else [default] * n

            frames.append(pd.DataFrame({
                "expiry": [_dt.datetime.fromtimestamp(t).date() for t in body["expiration"]],
                "right": ["C" if s == "call" else "P" for s in body["side"]],
                "strike": col("strike"),
                "bid": col("bid"), "ask": col("ask"), "last": col("last"),
                "volume": col("volume", 0), "open_interest": col("openInterest", 0),
                "iv": col("iv"),
            }))

        if not frames:
            raise RuntimeError(f"marketdata: no option data returned for {symbol}")
        if spot is None:
            spot = float(history["close"].iloc[-1])
            warnings.append("marketdata: no underlying price in the chain, using last close")

        df = pd.concat(frames, ignore_index=True)

        if self.credits_remaining is not None:
            warnings.append(
                f"marketdata: {self.credits_used} credits used this pull, "
                f"{self.credits_remaining:,} remaining today")
            if self.credits_remaining < 2000:
                warnings.append(
                    "marketdata: fewer than 2,000 credits left -- a full two-symbol "
                    "scan costs roughly 5,000, so the next one may be truncated")

        asof = _dt.datetime.now()
        return ChainSnapshot(
            symbol=symbol, spot=float(spot),
            chain=self._finalise(df, asof), asof=asof,
            source=f"{self.name}{'/otm' if self.otm_only else ''}",
            history=history, warnings=warnings,
        )
