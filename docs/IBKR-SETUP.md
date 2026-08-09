# Connecting Interactive Brokers for live data

## The constraint you have to design around

**The IBKR API is a socket on `localhost`. Nothing outside your machine can reach it.**

There is no IBKR cloud API for market data. TWS and IB Gateway open a TCP port on
127.0.0.1, and the only way to get data out is to run code on the same machine.
No token, no webhook, no hosted endpoint.

That means "live data all the time" has exactly one shape: **your Mac stays on,
IB Gateway stays logged in, and a scheduled local job pulls on an interval.**
Everything else in this document is in service of that.

Three deployment patterns, and what each actually gives you:

| Pattern | Live IBKR data | Survives Mac being off | Setup |
|---|---|---|---|
| **A. Local only** | Yes, real-time | No | Gateway + launchd collector |
| **B. Cloud routine only** | No — Yahoo, 15-min delayed | Yes | already running |
| **C. Local collector → git → cloud agent** | Yes, with a lag equal to your push interval | Reads last push | A + `--push` + private remote |

Pattern **C** is the one that makes a cloud agent able to reason over live IBKR
numbers: the Mac does the pulling, pushes the derived series to a private repo,
and anything elsewhere reads that. The bridge is git, not the API.

For positioning work the delay matters less than you would think. Open interest
— which drives GEX, the flip level, max pain and the OI walls — **updates once
per day**, published by OCC before the open. Real-time quotes improve IV and
skew readings; they do not change the positioning picture.

---

## 1. Account and software

**Account.** Any IBKR account works, including a free paper account. Paper
accounts often carry weaker data entitlements, so `ib_check.py` flags it.

**Software — use IB Gateway, not TWS.** Gateway is the headless version: same
API, a fraction of the memory, no charting UI to crash.

Download: [interactivebrokers.com/en/trading/ibgateway-stable.php](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)

Ports, which you will need to recognise:

| | Live | Paper |
|---|---|---|
| IB Gateway | 4001 | 4002 |
| TWS | 7496 | 7497 |

The adapter probes all four, so you do not have to configure which one.

---

## 2. Enable the API

In **IB Gateway**: `Configure → Settings → API → Settings`
In **TWS**: `File → Global Configuration → API → Settings`

- [x] **Enable ActiveX and Socket Clients** — required
- [x] **Read-Only API** — keep this ON. This project only reads; leaving it on
      means a bug here can never submit an order.
- [ ] **Allow connections from localhost only** — leave ON (default)
- **Trusted IPs**: add `127.0.0.1`
- **Socket port**: leave at the default for your mode

Restart Gateway after changing these.

---

## 3. Market data subscriptions

This is the part that actually costs money and the part people get wrong.

`Account Management → Settings → Market Data Subscriptions`

**First, declare non-professional status** (`Settings → Market Data Subscriber
Status`). Professional pricing for OPRA is roughly 20× non-professional. If you
trade your own money and are not registered or using the data for a business,
you are non-professional — but answer honestly, IBKR audits this.

Then subscribe, in this order:

1. **US Securities Snapshot and Futures Value Bundle** — ~$10/month
   *Waived entirely if you pay more than $30/month in commissions.*
   Gives you the underlying quote. Without it you get nothing.

2. **US Equity and Options Add-On Streaming Bundle** — ~$4.50/month non-pro
   Requires #1. This is **OPRA** — the options data itself: streaming option
   quotes, implied vol, and the **open interest ticks** that GEX depends on.

Prices drift; check the subscription page for current figures.

**If you skip these:** the adapter automatically steps down to delayed data
(15 minutes) and still works. Delayed data usually does not carry open
interest, in which case `daily_report.py --source yahoo` is genuinely the
better choice — Yahoo publishes correct end-of-day OI for free, and OI is a
daily number anyway.

---

## 4. Verify

With Gateway running and logged in:

```bash
cd ~/options-desk
./.venv/bin/python scripts/ib_check.py
```

It tests five layers in order and tells you which one fails:

```
1. TCP    is anything listening on the API ports
2. API    does the handshake succeed
3. QUOTE  do we get a live underlying price       <- entitlement layer
4. CHAIN  does the option chain definition load
5. OPRA   does a real contract return bid/ask, IV and OPEN INTEREST
```

Layer 5 is the one that decides whether GEX and max pain are trustworthy from
IBKR. If it warns that open interest is missing, use `--source yahoo` for the
positioning metrics until the OPRA bundle is active.

Once it passes:

```bash
./.venv/bin/python scripts/daily_report.py --source ibkr
```

---

## 5. Keeping Gateway alive

Gateway **force-logs-out once every 24 hours**. Left alone, your collector dies
quietly overnight.

**Configure → Settings → Lock and Exit → Auto restart** (not auto log-off).
Gateway then restarts itself daily without credentials. You still have to log in
manually about once a week, typically after the Sunday maintenance window.

To remove that last manual step, use **IBC**:
[github.com/IbcAlpha/IBC](https://github.com/IbcAlpha/IBC) — it drives the
Gateway login screen from a config file and restarts on disconnect. It stores
your IBKR password on disk, so treat that machine accordingly. Set it up
yourself; this project deliberately does not touch your credentials.

Also: **stop the Mac from sleeping**, or the collector stops with it.

```bash
sudo pmset -a sleep 0 disablesleep 1     # revert with disablesleep 0
```

---

## 6. Continuous collection

```bash
# every 5 minutes, GLD + QQQ, regular trading hours only
./.venv/bin/python scripts/install_launchd.py --job collect --interval 300

# check both jobs
./.venv/bin/python scripts/install_launchd.py --status

# remove it
./.venv/bin/python scripts/install_launchd.py --job collect --uninstall
```

The intraday collector is only worth running **once Gateway is up**. On Yahoo
data it re-reads the same once-a-day open interest every five minutes, which
tells you nothing new. The `--job daily` agent is the one that matters without
a broker connection.

The job runs on a fixed interval around the clock; the collector itself no-ops
outside 09:30–16:00 ET. Each pass appends one row per symbol to
`data/live/intraday-YYYY-MM-DD.csv`:

```
ts_ny, symbol, spot, gex_total, flip_level, spot_vs_flip_pct, regime,
iv30, rv20, vrp, skew_front, term_slope, vanna, charm, pcr_oi, ...
```

Full chains are deliberately **not** stored — 60 KB per symbol per pull is half
a gigabyte a year of data that is worthless ten minutes after it is written. The
derived series is what has lasting value: it shows you the flip level migrating
during the session, which is a signal a daily snapshot cannot produce.

`--interval 300` is a sensible default. Below ~60 seconds you are re-pulling
hundreds of option lines faster than OI or IV meaningfully change, and you will
start hitting IBKR pacing limits.

---

## 7. Making live data reachable from the cloud agent (pattern C)

Give the repo a **private** remote, then add `--push`:

```bash
cd ~/options-desk
gh repo create options-desk --private --source=. --remote=origin
git push -u origin main

./.venv/bin/python scripts/install_launchd.py --interval 300 --push
```

Every collection now commits and pushes the intraday CSV. The scheduled cloud
agent clones the repo and reads real IBKR-derived numbers instead of falling
back to Yahoo.

Keep the remote private. The derived series exposes what you watch and when.

---

## Troubleshooting

**"nothing is listening on any API port"**
Gateway is not running, not logged in, or the API checkbox is off.

**Handshake times out**
Another process is holding that client ID. `python scripts/ib_check.py --client-id 123`.
Or a modal dialog is waiting inside Gateway — look at the window.

**Quotes come back empty but the connection is fine**
No market-data subscription. The adapter falls back to delayed automatically and
records a warning in the report; `ib_check.py` names the specific bundle to buy.

**Open interest is always zero**
OPRA bundle is not active, or you are on delayed data. Use `--source yahoo` for
positioning metrics — genuinely the correct call here, not a workaround.

**`Error 200: No security definition has been found`**
Wrong `tradingClass` or an expiry that does not exist for that symbol. Both come
from `reqSecDefOptParams`, so this usually means the symbol has no SMART-routed
100-multiplier chain.

**Collector stopped overnight**
Gateway's daily logout. See §5.
