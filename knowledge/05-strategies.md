# 5. Strategy taxonomy

Every options strategy is a bet on some combination of four things: **direction
(delta), movement (gamma), time (theta), and volatility (vega).** Organise them
by what they are actually long and short and the whole space collapses into
something learnable.

## The master table

| Strategy | Structure | Δ | Vega | Theta | Max profit | Max loss | Use when |
|---|---|---|---|---|---|---|---|
| Long call | Buy call | + | + | − | Unlimited | Premium | Bullish, want defined risk, IV low |
| Long put | Buy put | − | + | − | Strike−0 | Premium | Bearish, want defined risk, IV low |
| Short call (naked) | Sell call | − | − | + | Premium | **Unlimited** | Almost never alone |
| Short put | Sell put | + | − | + | Premium | Large | Bullish + IV high + willing to own |
| Covered call | Long 100sh + short call | + | − | + | Capped | Stock to 0 | Own stock, want income, capped upside OK |
| Cash-secured put | Short put + cash | + | − | + | Premium | Large | Want to be assigned lower |
| **Vertical spreads** |
| Bull call spread | Buy call, sell higher call | + | ± | ± | Capped | Capped | Moderately bullish, defined risk |
| Bear put spread | Buy put, sell lower put | − | ± | ± | Capped | Capped | Moderately bearish |
| Bull put spread | Sell put, buy lower put | + | − | + | Credit | Capped | Bullish + high IV (credit version) |
| Bear call spread | Sell call, buy higher call | − | − | + | Credit | Capped | Bearish + high IV (credit version) |
| **Volatility structures** |
| Long straddle | Buy ATM call + put | ~0 | ++ | −− | Unlimited | Both premiums | Expect a big move, IV low |
| Long strangle | Buy OTM call + put | ~0 | ++ | −− | Unlimited | Both premiums | Same, cheaper, needs bigger move |
| Short straddle | Sell ATM call + put | ~0 | −− | ++ | Credit | **Unlimited** | High IV, expect pinning. Dangerous. |
| Short strangle | Sell OTM call + put | ~0 | −− | ++ | Credit | **Unlimited** | Same, wider, higher win rate |
| Iron condor | Short strangle + long wings | ~0 | − | + | Credit | **Capped** | The adult version of a short strangle |
| Iron butterfly | Short straddle + long wings | ~0 | − | + | Credit | Capped | Higher credit, narrower profit zone |
| **Time structures** |
| Calendar spread | Sell near, buy far, same strike | ~0 | + | + | Capped | Debit | Expect pinning + term structure normalisation |
| Diagonal | Sell near, buy far, diff strike | ± | + | + | Capped | Debit | Directional + time decay |
| **Hedges** |
| Collar | Long stock + long put + short call | + | ± | ± | Capped | Capped | Protect a position cheaply |
| Protective put | Long stock + long put | + | + | − | Unlimited | Capped | Insurance on a holding |
| Risk reversal | Short put + long call | ++ | ± | ± | Unlimited | Large | Bullish, financed by selling skew |

## The four questions that pick the structure

Ask them in this order. The answers determine the trade almost mechanically.

**1. Direction?** Up / down / sideways / no view
**2. Is IV rich or cheap?** (IV rank + VRP)
**3. What is the gamma regime?** (long gamma = range; short gamma = trend)
**4. What is my defined risk?** Always answer this before entering.

The decision grid:

| | **IV cheap (buy premium)** | **IV rich (sell premium)** |
|---|---|---|
| **Bullish** | Long call, call debit spread | Bull put spread, cash-secured put |
| **Bearish** | Long put, put debit spread | Bear call spread |
| **Sideways** | Calendar spread | Iron condor, iron butterfly |
| **Big move, no direction** | Long straddle / strangle | — (do not sell into this) |

## The strategies that actually matter for reading the market

Most retail material treats all of these as equal. They are not. For the purpose
of *understanding market direction* rather than placing trades, three matter
disproportionately:

**Collars (JPM JHEQX and peers).** Enormous, systematic, on a known schedule.
They create the strike clusters that dealers hedge around and suppress vol at
specific tenors. Knowing where the collar strikes sit tells you where the market
has artificial support and resistance.

**Covered-call / put-write ETFs.** Now large enough that their monthly roll is a
visible supply of calls, structurally capping upside vol.

**Protective put buying by asset managers.** The source of skew, and the fuel for
every vanna rally.

## Risk management, honestly

The strategy is the easy part. Survival is the whole game.

- **Defined risk by default.** Naked short options can lose multiples of the
  account. An iron condor is a short strangle that lets you sleep.
- **Position sizing off max loss, never off margin.** Assume the worst case
  happens and ask whether you survive it.
- **A 90% win rate means nothing on its own.** A strangle that wins 90% of the
  time collecting $83 while risking thousands is a negative-expectancy trade in
  disguise. Always compute `win% × avg_win − loss% × avg_loss`.
- **The mark-to-market path matters as much as the expiry payoff.** A short put
  that expires profitable can still show a −$24,000 unrealized loss on the way
  there. If you cannot hold that, the expiry math is irrelevant.
- **Short gamma near expiry is where accounts die.** Gamma explodes in the last
  days. A 0DTE short strangle can go from comfortable to catastrophic in
  minutes.
- **Check VRP before every short-premium trade.** Negative VRP means you are
  selling insurance below cost.
- **Know your assignment risk.** American-style, ex-dividend dates, AM vs PM
  settlement.

## The realistic edge for an individual

Not out-trading market makers on price. It is:

1. **Regime selection** — only selling premium when long gamma AND positive VRP.
2. **Patience** — no mandate to be in the market.
3. **Public positioning data** — GEX, flip levels and OI walls are free and
   mostly ignored by retail.
4. **Defined risk always** — so a single tail event cannot end the account.

---

**See also:** [04-vol-surface.md](04-vol-surface.md) · [07-daily-playbook.md](07-daily-playbook.md)
