# options-desk

Options positioning and volatility analysis for gold (GLD) and the Nasdaq (QQQ).

Answers one question every morning: **what regime have dealer hedging flows and
the volatility surface put this market into, and what gets paid in that regime?**

It is a positioning read, not a price forecast, and not financial advice.

## Quick start

```bash
./scripts/bootstrap.sh                                  # picks a suitable Python, installs, verifies
./.venv/bin/python scripts/daily_report.py              # the daily report
./.venv/bin/python scripts/scan.py --dte 0 45           # ranked structure candidates
./.venv/bin/python scripts/watch.py                     # one watcher pass
./.venv/bin/python -m pytest tests/ -q                  # 19 tests
```

Data comes from IB Gateway when it is running and Yahoo otherwise, decided by a
0.3 ms TCP probe. No broker account is needed for anything here.

## What it computes

**Positioning** (`metrics.py`) — gamma exposure by strike, the modelled
zero-gamma flip level, vanna and charm exposure, 25-delta skew, term structure,
volatility risk premium, max pain, OI walls, expected move.

**The surface** (`surface.py`) — Gatheral SVI fitted per expiry against a
put-call-parity-implied forward, static arbitrage checks, and the risk-neutral
density via Breeden-Litzenberger. Fits worse than 2 vol points RMSE are
rejected rather than returned, and `SurfaceFits.rejected` says why.

**Structures** (`structures.py`, `scanner.py`) — multi-leg construction,
executable pricing, net greeks, and expected value against a **required**
density argument.

**Alerting** (`alerts.py`, `watch.py`) — every rule fires on a state change,
never on a level.

## The one thing to understand before using this

Under the risk-neutral density recovered from option prices, the expected profit
of **every** structure is zero minus transaction costs. That is the definition
of the density, not a claim about markets: it is the measure that reprices every
listed option back to its own market price.

So there is no structure that is high expected value by virtue of its shape, its
greeks, or its probability of profit. An edge exists only where your
distribution differs from the market's — from the empirical record, from a
stated view, or from a genuine mispricing.

`evaluate()` requires the density as an argument for exactly this reason. The
scanner reports both `edge` (better than the market's own pricing) and a
`verdict` column (does it actually make money after crossing the spread). Those
are different things and are kept visibly separate: on a recent GLD scan, five
candidates beat the market's pricing and **zero** had positive expectancy once
slippage was paid.

## Scheduling

```bash
./scripts/install_launchd.py --job daily --at 15:30 --open   # report each weekday
./scripts/install_launchd.py --job watch --interval 600 --notify
./scripts/install_launchd.py --status
```

A cloud routine publishes the same report as a shareable page each weekday.

## Agents

`options-analyst` (regime and direction), `vol-surface-quant` (the surface
itself), `structure-designer` (what to trade, or nothing), `flow-hunter`
(intraday and short-dated).

## Knowledge base

Ten chapters in `knowledge/`: market structure, expiration mechanics, dealer
flows, the vol surface, strategy taxonomy, the players, the daily playbook, what
the model assumes and where it breaks, risk and sizing, and reading flow.

## Interactive Brokers

`docs/IBKR-SETUP.md`. The short version: the IBKR API is a localhost socket, so
"live all the time" means your machine stays on with Gateway logged in. Open
interest — which drives GEX, the flip, max pain and the walls — updates once a
day anyway, so Yahoo is genuinely sufficient for the positioning work.

## Layout

```
optionsdesk/
  blackscholes.py   pricing, first and second order greeks, IV inversion
  metrics.py        positioning and volatility metrics
  surface.py        SVI fitting, arbitrage checks, risk-neutral density
  structures.py     multi-leg construction, pricing, expected value
  scanner.py        candidate generation and ranking
  alerts.py         change-only alert rules
  report.py         orchestration
  render.py         HTML dashboard
  sources/          IBKR and Yahoo adapters behind one contract
scripts/            bootstrap, daily_report, scan, watch, collect, ib_check, install_launchd
knowledge/          ten chapters
tests/              19 tests against a synthetic market with a known answer
```

## Why there are so many tests for a personal project

Nine real bugs were found here, every one by checking a mathematical identity
rather than by reading the code: present versus future value, a truncated
integration grid, an assumed forward, sample drift, Jensen's inequality in the
recentring, density truncation, fitting deep-ITM options, a hardcoded market
data type, and an install that failed silently.

Several of them made short-premium structures look like free money. That is the
specific failure mode this project exists to avoid, so the identities are now
locked in `tests/`.
