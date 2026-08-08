# 7. Daily playbook: reading the report in five minutes

The order below is deliberate. Each step can override the one before it.

## Step 1 — Where are we in the expiration cycle?

Before any number. Check the calendar:

- **Days before monthly OPEX?** Expect pinning, expect charm drift.
- **The Monday after OPEX?** Prior regime is void. Read everything fresh.
- **Triple witching week (Mar/Jun/Sep/Dec)?** Expect abnormal volume and a
  higher chance of a regime break afterwards.
- **Quarter end?** The JPM collar rolls. Strike clusters move.

## Step 2 — Gamma regime and the flip level

The dominant read.

| Reading | Behaviour to expect | What gets paid |
|---|---|---|
| **Positive GEX, spot well above flip** | Range-bound, vol suppressed, dips bought | Range structures, fading extremes |
| **Positive GEX, spot near flip** | Fragile. One flush flips the regime | Reduce size. Respect the level. |
| **Negative GEX, spot below flip** | Trending, amplified moves, gap risk | Long convexity, defined risk, directional |

The distance from spot to flip is your cushion. Note it as a **level to watch
intraday** — crossing it is a genuine regime change, not a chart line.

## Step 3 — Is volatility cheap or expensive? (VRP, IV rank, term structure)

This determines *which structure*, independent of Step 2.

- **VRP positive** → sellers are being paid. Short premium is viable.
- **VRP negative** → sellers are underpaid. **Do not sell naked premium.**
  Favour debit spreads, calendars, long convexity.
- **Term structure inverted** → stress. The market is paying up for immediate
  protection. Treat as a warning regardless of what gamma says.

**Steps 2 and 3 routinely disagree**, and that disagreement is information, not
noise. "Pinned but underpriced" — dealers dampening moves while realized vol runs
above implied — means respect the range for *direction* but do not sell it for
*premium*. The report flags this conflict explicitly.

## Step 4 — Skew: who is hedging, and how urgently?

- Steep and steepening → active downside hedging. Fear building.
- Extremely steep → increasingly contrarian; that put inventory is vanna fuel.
- Flat → complacency, or upside chase.
- **Gold:** flat or negative skew is normal. It is not a bearish signal there.

## Step 5 — Vanna and charm: the flow with no news behind it

- **Negative vanna exposure** → falling IV mechanically generates dealer buying.
  This is the "melt-up on nothing" setup. Especially after FOMC/CPI/earnings.
- **Charm** → the calendar drift, strongest in the last two sessions before a
  monthly expiry.

If you cannot explain a grind higher on zero news, this is usually why.

## Step 6 — The map: max pain, OI walls, expected move

- **Expected move** → the honest range for the period. Do not sell strikes inside
  it and call it conservative.
- **Call wall** → resistance created by hedging, not by chart geometry.
- **Put wall** → support, same logic.
- **Max pain** → weak magnet. Confirmation only, and only into monthly expiry
  with heavy OI. Ignore it for 0DTE and thin weeklies.

## Step 7 — Write down what would prove you wrong

The discipline that makes the rest useful. Before acting:

- Which level, if crossed, invalidates the regime read? (Usually the flip.)
- What is the max loss on the structure, in dollars?
- Can I hold the mark-to-market path, not just the expiry payoff?

---

## The four regimes, condensed

**Pinned / vol-suppressed** — long gamma, positive VRP, contango.
Range strategies, iron condors, fade extremes toward gamma strikes. The only
regime where naked-ish short premium is genuinely compensated.

**Pinned but underpriced** — long gamma, *negative* VRP.
The pin is real but you are not paid to sell it. Calendars, debit spreads,
directional structures using the range for entry timing rather than for premium.

**Unstable** — short gamma.
Moves get amplified. Size down. Defined risk only. Respect the flip level as the
line that matters. Directional structures work better than range ones.

**Stressed / trend-amplifying** — short gamma AND inverted term structure.
The configuration in which short-premium books break. Long convexity, defined
risk, or no position. This is not a "sell the fear" regime until the term
structure un-inverts.

---

## Non-negotiables

1. This is a **positioning read, not a forecast.** It says how price is likely to
   behave, not which way it will go.
2. Every exposure number rests on the **dealer sign convention** (long calls,
   short puts). It is a convention, not truth.
3. **Recompute daily.** Flip levels and walls move as open interest changes.
4. Yahoo data is **~15 min delayed**; open interest updates once daily. Fine for
   positioning, not for execution.
5. **Defined risk always.** No read is good enough to justify unlimited downside.
6. Educational and informational only. Not investment advice.

---

**See also:** [03-dealer-flows.md](03-dealer-flows.md) · [05-strategies.md](05-strategies.md)
