"""Macro event calendar: FOMC, CPI, NFP -- the releases that actually move IV.

Dealer positioning and the vol surface describe the STATIC state of the
market. They say nothing about a scheduled shock two days away. A short-vega
structure that looks fine against today's surface can be a very different bet
once you notice its expiry straddles a CPI print.

DATA SOURCE AND HONESTY POLICY
-------------------------------
FOMC dates are published by the Federal Reserve itself, a year or more in
advance, and are confirmed here from federalreserve.gov (fetched 2026-08-10).
CPI and NFP dates are published by the Bureau of Labor Statistics on the same
horizon and are confirmed here from two independent sources that agreed on
every date.

These are NOT computed from a "first Friday of the month" rule applied
blindly -- 2026 already has two exceptions to that rule for NFP alone (a
government-shutdown delay in January, a holiday shift in July), which is
exactly why hardcoding a rule instead of the actual published dates would be
wrong on real dates in a real year. The table below is the real published
schedule, transcribed once, not derived.

**This table needs a human to refresh it every few months.** BLS publishes
next year's calendar in the preceding autumn; FOMC dates for a new year are
published while the current year is still running. Nothing here re-fetches
automatically -- an event with no future dates just stops appearing, silently.
`data_freshness()` exists so a caller can notice that before it becomes a
blind spot.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

__all__ = ["MacroEvent", "EVENTS", "upcoming", "events_before",
           "expiry_risk", "data_freshness"]


@dataclass(frozen=True)
class MacroEvent:
    date: _dt.date
    kind: str            # 'FOMC' | 'CPI' | 'NFP'
    label: str
    time_et: str
    impact: str           # 'high' | 'medium'

    def __str__(self):
        return f"{self.date.isoformat()} {self.kind} ({self.time_et} ET)"


# FOMC 2026 -- federalreserve.gov/monetarypolicy/fomccalendars.htm
# Statement ~14:00 ET on the second day; presser ~14:30 ET at every meeting
# starting in 2019. Meetings with economic projections (Mar/Jun/Sep/Dec) tend
# to move markets harder than the others.
_FOMC_2026 = [
    ("2026-01-28", "January FOMC decision"),
    ("2026-03-18", "March FOMC decision + projections"),
    ("2026-04-29", "April FOMC decision"),
    ("2026-06-17", "June FOMC decision + projections"),
    ("2026-07-29", "July FOMC decision"),
    ("2026-09-16", "September FOMC decision + projections"),
    ("2026-10-28", "October FOMC decision"),
    ("2026-12-09", "December FOMC decision + projections"),
]

# CPI 2026 -- bls.gov/schedule, cross-confirmed via usinflationcalculator.com
# and macroornoise.com (identical on every date). 08:30 ET.
_CPI_2026 = [
    ("2026-01-13", "December 2025 CPI"),
    ("2026-02-13", "January 2026 CPI"),
    ("2026-03-11", "February 2026 CPI"),
    ("2026-04-10", "March 2026 CPI"),
    ("2026-05-12", "April 2026 CPI"),
    ("2026-06-10", "May 2026 CPI"),
    ("2026-07-14", "June 2026 CPI"),
    ("2026-08-12", "July 2026 CPI"),
    ("2026-09-11", "August 2026 CPI"),
    ("2026-10-14", "September 2026 CPI"),
    ("2026-11-10", "October 2026 CPI"),
    ("2026-12-10", "November 2026 CPI"),
]

# NFP / Employment Situation 2026 -- bls.gov schedule. 08:30 ET. NOT a clean
# "first Friday" rule: January was pushed by a government shutdown, April
# landed on the second Friday under the revised post-shutdown calendar, and
# July moved to Thursday for the July 4th holiday. November's exact date was
# not yet published as of the August 2026 source check -- left out rather
# than guessed.
_NFP_2026 = [
    ("2026-02-11", "January 2026 jobs report"),
    ("2026-03-06", "February 2026 jobs report"),
    ("2026-04-03", "March 2026 jobs report"),
    ("2026-05-08", "April 2026 jobs report"),
    ("2026-06-05", "May 2026 jobs report"),
    ("2026-07-02", "June 2026 jobs report"),
    ("2026-08-07", "July 2026 jobs report"),
    ("2026-09-04", "August 2026 jobs report"),
    ("2026-10-02", "September 2026 jobs report"),
    ("2026-11-06", "October 2026 jobs report"),
]

_SOURCE_CHECKED = _dt.date(2026, 8, 10)


def _build() -> list[MacroEvent]:
    out = []
    for d, label in _FOMC_2026:
        out.append(MacroEvent(_dt.date.fromisoformat(d), "FOMC", label, "14:00", "high"))
    for d, label in _CPI_2026:
        out.append(MacroEvent(_dt.date.fromisoformat(d), "CPI", label, "08:30", "high"))
    for d, label in _NFP_2026:
        out.append(MacroEvent(_dt.date.fromisoformat(d), "NFP", label, "08:30", "medium"))
    return sorted(out, key=lambda e: e.date)


EVENTS: list[MacroEvent] = _build()


def upcoming(days_ahead: int = 7, today: _dt.date | None = None) -> list[MacroEvent]:
    """Events in [today, today + days_ahead], inclusive."""
    today = today or _dt.date.today()
    horizon = today + _dt.timedelta(days=days_ahead)
    return [e for e in EVENTS if today <= e.date <= horizon]


def events_before(deadline: _dt.date, today: _dt.date | None = None) -> list[MacroEvent]:
    """Events in [today, deadline]. Built for 'does this expiry contain a print'."""
    today = today or _dt.date.today()
    return [e for e in EVENTS if today <= e.date <= deadline]


def expiry_risk(expiry: _dt.date, today: _dt.date | None = None) -> dict:
    """Does a specific expiry's remaining life contain a scheduled event?

    This is the number that actually matters for a position: not "is there an
    event this week" in the abstract, but "does MY structure's window contain
    one". A weekly credit spread that expires the Friday after a Wednesday CPI
    print carries a vega and gap risk its greeks alone do not show, because the
    greeks are a snapshot and the print is a discontinuity.
    """
    today = today or _dt.date.today()
    inside = events_before(expiry, today)
    return {
        "expiry": expiry,
        "events": inside,
        "has_high_impact": any(e.impact == "high" for e in inside),
        "count": len(inside),
    }


def data_freshness(today: _dt.date | None = None) -> dict:
    """Is the calendar running out of runway, and how stale is the source?"""
    today = today or _dt.date.today()
    future = [e for e in EVENTS if e.date >= today]
    last = max((e.date for e in EVENTS), default=None)
    return {
        "source_checked": _SOURCE_CHECKED.isoformat(),
        "days_since_check": (today - _SOURCE_CHECKED).days,
        "last_date_in_table": last.isoformat() if last else None,
        "events_remaining": len(future),
        "needs_refresh": last is None or (last - today).days < 30,
    }
