# options-desk

Options positioning and volatility analysis for gold (GLD) and the Nasdaq (QQQ).

Answers one question every morning: **what regime have dealer hedging flows and
the volatility surface put this market into, and what gets paid in that regime?**

It is a positioning read, not a price forecast.

## Quick start

```bash
cd ~/options-desk
./.venv/bin/python scripts/daily_report.py
```

Writes `out/report-YYYY-MM-DD.html` (dashboard) and `.json` (structured), and
prints a terminal digest.

```bash
--symbols QQQ,GLD,SPY   # which tickers
--source ibkr           # force IBKR; fails if TWS/Gateway is down
--source yahoo          # free, ~15 min delayed
--source auto           # default: IBKR, falling back to Yahoo
--expiries 8            # expiries to pull
--no-persist            # don't append to IV history
```

## What it computes

**Pricing** — Black-Scholes with continuous carry; delta, gamma, vega, theta,
vanna, charm, vomma; implied-vol inversion by Brent with no-arbitrage bounds.

**Volatility** — realized vol and its 1-year cone, IV30 interpolated in variance
space, the volatility risk premium (IV − RV), IV rank and percentile, ATM term
structure with contango/backwardation classification, 25-delta skew.

**Positioning** — gamma exposure by strike, net GEX, the modelled zero-gamma
flip level, aggregate vanna and charm exposure, put/call ratios.

**Expiration mechanics** — max pain, expected move (both σ-based and straddle),
open-interest walls, per-expiry detail.

**Synthesis** — a regime verdict that treats gamma positioning and the VRP as
*independent* axes and flags the conflict when they disagree, rather than
collapsing them into one confident answer.

## Data sources

| Source | Latency | Needs | Notes |
|---|---|---|---|
| IBKR | real-time | TWS or IB Gateway running locally, API enabled | Ports tried: 7496, 7497, 4001, 4002 |
| Yahoo | ~15 min | nothing | Always available, including from a cloud run |

`auto` tries IBKR and falls back to Yahoo, recording the reason in the report's
data notes. **IBKR is localhost-only** — a scheduled cloud run will always use
Yahoo. Open interest, the input that matters most here, updates once daily on
both, so the delay is not a meaningful handicap for positioning work.

## Layout

```
optionsdesk/
  blackscholes.py   pricing, greeks, IV inversion (validated vs numerical derivatives)
  metrics.py        vol surface, GEX, vanna/charm, max pain, expected move
  report.py         orchestration + regime synthesis + IV history persistence
  render.py         self-contained themed HTML dashboard, inline SVG charts
  sources/
    base.py         ChainSnapshot contract + normalisation
    ibkr.py         Interactive Brokers adapter
    yahoo.py        yfinance adapter
scripts/
  daily_report.py   CLI entry point
knowledge/          the reference material the agent reads (7 documents)
data/history/       accumulating daily IV observations, for IV rank
out/                generated reports
```

## The agent

A specialist subagent is installed at `~/.claude/agents/options-analyst.md`, and
a skill at `~/.claude/skills/options-desk/`. Invoke with `/options-desk` for the
daily run, or ask the `options-analyst` agent anything about options pricing,
strategy selection or positioning.

## Knowledge base

`knowledge/` holds the domain material, written to be read by the agent:

1. Market structure — who is on the other side, and why dealer flow is knowable
2. Expiration mechanics — 0DTE through triple witching, pinning, settlement traps
3. Dealer flows — GEX, flip levels, vanna, charm, the JPM collar, vol-control funds
4. The volatility surface — IV vs RV, VRP, skew, term structure, IV rank
5. Strategy taxonomy — the full grid, selection logic, risk management
6. Players and edge — the firms, the traders, and the five kinds of edge
7. Daily playbook — the seven-step reading order and the four regimes

## Known limits

- Dealer sign convention (long calls / short puts) is an **assumption**. Most
  reliable on index and mega-ETF products; least reliable on single names.
- The flip level is a **model output** and moves daily with open interest.
  Recompute it every day; last week's level is worthless.
- IV rank requires history. It reports "still building" below 20 observations
  rather than quoting a fake number.
- Max pain is weak evidence — confirmation only, into monthly expiry.
- Nothing here predicts news, earnings or macro shocks.

## Disclaimer

Educational and informational only. Not investment advice, and not a
recommendation to buy or sell anything. Options carry a risk of total loss, and
short option positions can lose considerably more than the capital committed.
