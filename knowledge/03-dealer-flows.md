# 3. Dealer flows: the mechanical engine under price

This is the core chapter. Everything the daily report computes lives here.

## The premise

A dealer who sells you a call is short that call. To stay directionally neutral
they buy shares equal to the option's delta. But **delta is not constant** — it
changes with price (gamma), with volatility (vanna), and with time (charm). Each
time delta changes, the dealer must trade the underlying again.

Those forced trades are large, mechanical, and predictable from public open
interest. They are the closest thing to a knowable flow in the market.

## Gamma exposure (GEX)

### The formula

```
GEX_strike = Γ × OI × 100 × S² × 0.01        (sign: + for calls, − for puts)
GEX_total  = Σ GEX_strike
```

Units: **dollars of underlying the dealer must trade per 1% move in spot.**

The sign convention is the market standard: dealers are assumed **net long calls
and net short puts**, because the flow they absorb is customers overwriting calls
(selling them) and buying protective puts. Hence `calls − puts`.

> **This assumption is a convention, not observed truth.** It holds well for
> index and large-ETF products dominated by retail and institutional hedging. It
> breaks when a single large customer runs the other way. Every GEX number
> anywhere — SpotGamma, MenthorQ, this tool — carries this caveat. Treat GEX as a
> positioning estimate, never as fact.

### Reading it

**Positive total GEX — dealers long gamma:**
- They must **sell rallies and buy dips** to stay flat.
- Realized volatility gets suppressed.
- Ranges hold. Large-OI strikes act as magnets.
- Trend-following gets chopped up. Mean reversion works.

**Negative total GEX — dealers short gamma:**
- They must **buy rallies and sell dips**.
- Every move gets amplified by the hedging itself.
- Ranges expand, trends persist, gap risk rises.
- This is the configuration present in essentially every violent selloff.

### The zero-gamma flip level

The modelled spot price where aggregate GEX crosses zero. Computed by holding
each contract's IV fixed and repricing gamma across a grid of hypothetical spot
levels, then locating the sign change.

**This is the single most useful level the option market produces.**

- Above the flip → stability regime. Dips get bought mechanically.
- Below the flip → instability regime. Dips get sold mechanically.
- The flip is not static. It moves daily as open interest changes. **Recompute
  it every day.** A flip level from last week is worthless.

The practical rule: *the distance between spot and the flip is a measure of how
much cushion the market has.* Spot 5% above flip is a very different tape from
spot 0.3% above flip.

## Vanna: the flow that has nothing to do with price

**Vanna = ∂Δ/∂σ** — how delta changes when implied volatility changes, with spot
unchanged.

This is the mechanism behind the most confusing market behaviour there is: **the
market grinds higher for days after a scare, on no news.**

The sequence:
1. A shock hits. Customers buy puts. IV spikes.
2. Dealers absorb that put flow and hedge by shorting the underlying.
3. The shock passes. IV starts mean-reverting lower.
4. As IV falls, those put deltas shrink — the dealer's short hedge is now too
   large.
5. **They buy back stock to rebalance.** No news. Pure mechanics.
6. Buying pushes price up, which pushes IV down further, which triggers more
   vanna buying.

That is the "melt-up after the VIX collapses" pattern, and it is why buying puts
right after a spike so often loses money even when you were right about the
risk. You are fighting a mechanical bid.

Vanna flows are strongest **after FOMC, CPI, and earnings** — events that create
a large IV crush on a scheduled date.

## Charm: the flow that comes from the calendar

**Charm = ∂Δ/∂t** — how delta changes purely from time passing.

As expiry approaches, OTM deltas decay toward 0 and ITM deltas march toward 1.
Dealers must trade the underlying to track that migration, every single day,
regardless of what price does.

- Charm is strongest **in the final two sessions before a monthly expiry**.
- It produces a **directional tilt with no news** — the classic quiet Thursday
  and Friday drift into OPEX.
- Combined with vanna, it explains most of the "why is this market grinding up
  on zero volume" days.

## The full feedback loop

```
        price moves
             │
             ▼
    dealer delta changes  ◄──── vol changes (vanna)
             │                        ▲
             ▼                        │
    dealer hedges in underlying ──────┘
             │
             ▼
      price moves more
```

When dealers are **long gamma** this loop is negative feedback — it damps. When
they are **short gamma** it is positive feedback — it explodes. That single sign
change is the difference between a calm tape and a crash.

## Institutional flows that are large enough to matter by name

**The JPMorgan Hedged Equity Fund (JHEQX) collar.** ~$18bn of S&P exposure,
collared quarterly: sell a 3–5% OTM call, buy a put spread with the proceeds.
Contract sizes north of 40,000 per leg, billions in notional, rolled on a known
quarterly schedule (the last trading day of the quarter). Effects:

- Structurally **suppresses implied vol** at that quarterly tenor, especially in
  OTM calls.
- Creates a large, known strike cluster that dealers must hedge around.
- The roll itself forces coordinated dealer flow on a predictable date.

It is "always on, never adjusted", which makes it one of the most forecastable
flows in the market. Everyone on a professional desk knows the strikes.

**Vol-control and risk-parity funds.** Systematically size positions inversely to
realized volatility. When RV rises they mechanically sell equities; when it falls
they buy. Slow-moving, but very large, and it makes volatility itself
self-reinforcing.

**CTAs / managed futures.** Trend-following, triggered off moving-average and
breakout signals. They amplify moves once thresholds are crossed. Their trigger
levels are widely modelled by sell-side desks.

**Systematic put-selling and covered-call ETFs (JEPI, QYLD and peers).** Now
large enough that their monthly roll is a visible source of call supply,
suppressing upside vol.

## What "manipulation" actually means

You will see claims that institutions "push price to max pain" or "hunt stops".
The accurate version:

- **There is rarely intent.** Hedging is a legal obligation of running a book,
  not a scheme.
- **The effect is nonetheless real and large**, because the flows are enormous
  and simultaneous.
- **It is knowable in advance**, because open interest is public data.
- Genuine illegal manipulation (marking the close, spoofing) exists and is
  prosecuted, but it is not what drives the daily patterns discussed here.

The useful mental shift: stop asking *"who is doing this to me"* and start asking
*"what is this book obligated to do next"*.

## What this framework cannot do

- It does not predict news, earnings surprises, or macro shocks.
- It says **how price will behave**, not **which direction it will go**.
- It degrades badly when open interest data is stale or wrong.
- Dealer-sign assumptions can be wrong for individual names — least reliable on
  single stocks, most reliable on index and mega-ETF products (SPX, SPY, QQQ).
- Every level it produces is a **model output**, sensitive to the IV surface used.

---

**See also:** [04-vol-surface.md](04-vol-surface.md) · [07-daily-playbook.md](07-daily-playbook.md)
