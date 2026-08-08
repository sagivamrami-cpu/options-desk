# 2. Expiration mechanics: the calendar is a strategy

Most retail traders treat expiry as an administrative date. Professionals treat
the expiration calendar as one of the most reliable sources of structure in the
market, because open interest concentrates on known dates and unwinds on a known
schedule.

## The expiration ladder

| Type | When | Character |
|---|---|---|
| **0DTE** | Every trading day for SPX/QQQ/SPY-class products | Enormous volume, almost no open interest carry. Gamma is violent but evaporates by the close. |
| **Weekly** | Every Friday (plus Mon/Wed on major products) | The working expiry for most short-dated positioning. |
| **Monthly (OPEX)** | Third Friday | The big one. Institutional OI concentrates here. Index options settle **AM** on the Friday; equity options settle PM. |
| **Quarterly / Triple witching** | Third Friday of Mar, Jun, Sep, Dec | Index options, index futures and equity options expire together. Consistently among the highest-volume days of the year (NYSE volume often >150% of the 20-day average). |
| **LEAPS** | Jan, 1–3 years out | Long-dated, low gamma, mostly vega and delta. |

0DTE now represents **over 45% of SPX options volume**. The practical effect: the
market experiences a miniature expiration cycle every single day, with the same
mechanics — gamma concentration, hedge unwind, magnetic strikes — just at
smaller amplitude and without the multi-week OI buildup.

## Why OPEX week has a personality

Through the month, open interest builds up at round strikes. Dealers hedge that
OI. As the third Friday approaches, three things happen at once:

1. **Gamma concentrates.** Gamma is largest at-the-money and it explodes as time
   to expiry shrinks. The hedging required per point of movement grows sharply.
2. **Charm accelerates.** Deltas migrate toward 0 or 1 purely from time passing,
   forcing mechanical buying or selling with no news attached. This is why
   Wednesday–Friday of OPEX week often has a directional tilt of its own.
3. **The whole position then vanishes.** On the Monday after OPEX, the hedges
   supporting the prior regime are gone. The market is suddenly free.

**The post-OPEX window (the following Monday–Wednesday) is one of the most
studied "regime change" windows in the market.** A range that held for two weeks
frequently breaks in the days after monthly expiry — not because sentiment
changed, but because the hedging that was enforcing the range expired.

## Pinning

As price drifts toward a strike carrying heavy open interest, dealer hedging
pushes it back. Long-gamma dealers sell into strength and buy into weakness
around that strike, and the effect strengthens as gamma rises into expiry.

- Strongest into the **Friday close of a monthly expiry**.
- Requires **large OI at a specific strike** and **dealers net long gamma**.
- **Dissipates immediately after expiration.**
- Fails completely when dealers are short gamma, or when a real news shock
  overwhelms the hedging flow. Pinning is a tendency, not a rule.

## Max pain

The strike at which the **least total money is paid out to option holders** —
computed by summing intrinsic value owed across all open contracts at each
candidate settlement price and taking the minimum.

**Honest assessment.** Max pain is real but weak, and it is routinely oversold.
It is a *description of where open interest is clustered*, not evidence that
anyone is steering price there. Use it as:

- a **secondary** confirmation when it agrees with the gamma profile;
- most informative into **monthly** expiry with heavy OI;
- essentially noise for a 0DTE or a thin weekly.

If max pain is 3% away from spot two days before expiry, the realistic
interpretation is "there is a lot of OI over there", not "price will go there".

## Settlement traps that cost real money

- **AM vs PM settlement.** Index options (SPX, NDX) settle at the *opening*
  price on expiration Friday, computed from opening prints of every component.
  That value can differ substantially from Thursday's close and from Friday's
  regular open. Holding an index option through AM settlement is a genuine gap
  risk that most retail traders do not know exists.
- **Assignment on short options.** American-style equity/ETF options (GLD, QQQ)
  can be assigned any time. Short ITM calls face assignment risk around
  ex-dividend dates. Index options are European — no early assignment.
- **Pin risk.** A short option that settles fractionally in or out of the money
  leaves you uncertain whether you will be assigned. You can end up with an
  unhedged 100-share position over a weekend.

## The practical calendar rules

1. **Know where you are in the cycle before reading anything else.** Two days
   before triple witching is a different market from the Tuesday after it.
2. **Expect ranges to hold into monthly OPEX, and to break after it.**
3. **Fade extremes toward large-OI strikes only when dealers are long gamma.**
4. **Do not sell short-dated premium into an expiry you have not looked at.**
   Gamma near expiry is where accounts die.
5. **Treat the post-OPEX Monday as a fresh regime read**, not a continuation.

---

**See also:** [03-dealer-flows.md](03-dealer-flows.md) · [07-daily-playbook.md](07-daily-playbook.md)
