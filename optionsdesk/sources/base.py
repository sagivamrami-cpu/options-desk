"""Shared contract every data source must satisfy.

The rest of the package never imports a concrete source. It asks for a
`ChainSnapshot` and works off that, so swapping Yahoo for IBKR (or a paid feed
later) changes nothing downstream.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import pandas as pd

# Column contract for the `chain` frame. Anything producing a snapshot must
# emit exactly these columns, in these units.
CHAIN_COLUMNS = [
    "expiry",         # datetime64[ns] -- expiration date (naive, exchange date)
    "right",          # 'C' or 'P'
    "strike",         # float
    "bid", "ask",     # float, NaN when unquoted
    "mid",            # float, (bid+ask)/2 with last-price fallback
    "last",           # float
    "volume",         # float -- contracts traded today
    "open_interest",  # float -- contracts outstanding
    "iv",             # float, decimal (0.20 == 20%). NaN means "solve it yourself"
    "dte",            # float -- calendar days to expiry
    "T",              # float -- years to expiry, dte/365
]


@dataclass
class ChainSnapshot:
    """One symbol, one moment in time, every listed expiry we could pull."""

    symbol: str
    spot: float
    chain: pd.DataFrame
    asof: _dt.datetime
    source: str
    # Daily closes of the underlying, used for realized-vol and IV-rank work.
    # Index is a DatetimeIndex, single column 'close'.
    history: pd.DataFrame | None = None
    # Free-form notes from the adapter (fallback reasons, staleness warnings).
    warnings: list[str] = field(default_factory=list)

    def expiries(self) -> list[pd.Timestamp]:
        return sorted(self.chain["expiry"].unique())

    def for_expiry(self, expiry) -> pd.DataFrame:
        return self.chain[self.chain["expiry"] == pd.Timestamp(expiry)]

    def quality(self) -> dict:
        """Is this data actually usable, and for what?

        Exists because of a real incident: pre-market, Yahoo returned
        bid=ask=0 and open_interest=0 for every contract. The pipeline
        computed GEX over zero open interest, got zero, produced a report with
        a nan flip level and a nan max pain, and delivered it without a word.
        Nothing in the stack noticed that the inputs were empty.

        Positioning metrics (GEX, the flip level, max pain, OI walls) are
        built ENTIRELY from open interest. With no open interest they are not
        approximate -- they are meaningless, and must not be shown.
        """
        df = self.chain
        n = len(df)
        if n == 0:
            return {"usable_for_positioning": False, "usable_for_surface": False,
                    "total_open_interest": 0.0, "two_sided_fraction": 0.0,
                    "problems": ["chain is empty"]}

        total_oi = float(df["open_interest"].fillna(0).sum())
        two_sided = float(((df["bid"] > 0) & (df["ask"] > 0)).mean())
        priced = float((df["mid"] > 0).mean())

        problems = []
        if total_oi <= 0:
            problems.append(
                "open interest is zero across the whole chain -- GEX, the gamma "
                "flip, max pain and OI walls cannot be computed")
        if two_sided < 0.05:
            problems.append(
                f"only {two_sided:.0%} of contracts have a two-sided market -- "
                "the volatility surface cannot be fitted from mids alone")
        if priced < 0.5:
            problems.append(f"only {priced:.0%} of contracts carry a usable price")

        return {
            "usable_for_positioning": total_oi > 0,
            "usable_for_surface": two_sided >= 0.05,
            "total_open_interest": total_oi,
            "two_sided_fraction": two_sided,
            "priced_fraction": priced,
            "problems": problems,
        }

    def summary(self) -> str:
        exps = self.expiries()
        return (
            f"{self.symbol} @ {self.spot:.2f} via {self.source} -- "
            f"{len(self.chain):,} contracts across {len(exps)} expiries "
            f"({pd.Timestamp(exps[0]).date()} to {pd.Timestamp(exps[-1]).date()})"
        )


class ChainSource:
    """Interface. Subclasses implement `fetch`."""

    name = "base"

    def fetch(self, symbol: str, max_expiries: int = 8) -> ChainSnapshot:
        raise NotImplementedError

    # -- helpers shared by concrete adapters -------------------------------

    @staticmethod
    def _finalise(df: pd.DataFrame, asof: _dt.datetime) -> pd.DataFrame:
        """Normalise a raw adapter frame into the CHAIN_COLUMNS contract."""
        df = df.copy()

        for col in ("bid", "ask", "last", "volume", "open_interest", "iv", "strike"):
            if col not in df.columns:
                df[col] = float("nan")
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["expiry"] = pd.to_datetime(df["expiry"]).dt.normalize()
        df["right"] = df["right"].astype(str).str.upper().str[0]

        # Mid price: prefer a real two-sided market, fall back to last trade.
        two_sided = df["bid"].notna() & df["ask"].notna() & (df["ask"] > 0)
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
        df.loc[~two_sided, "mid"] = df.loc[~two_sided, "last"]

        # A zero bid with a live ask is normal for far OTM strikes; keep it, but
        # a crossed or absurd market is bad data and gets dropped downstream.
        df.loc[df["mid"] <= 0, "mid"] = float("nan")

        ref = pd.Timestamp(asof).normalize()
        df["dte"] = (df["expiry"] - ref).dt.days.astype(float)
        # Same-day expiry still has intraday life; treat it as a third of a day
        # so gamma stays finite instead of exploding to infinity.
        df.loc[df["dte"] <= 0, "dte"] = 0.33
        df["T"] = df["dte"] / 365.0

        df["volume"] = df["volume"].fillna(0.0)
        df["open_interest"] = df["open_interest"].fillna(0.0)

        return df[CHAIN_COLUMNS].sort_values(["expiry", "strike", "right"]).reset_index(drop=True)
