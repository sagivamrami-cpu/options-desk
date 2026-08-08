# 1. Market structure: who is actually on the other side

## The single most important fact

When you buy an option, you are almost never trading with another speculator.
You are trading with a **market maker** whose business is not direction. Their
business is capturing the bid-ask spread thousands of times a day while staying
delta-neutral. They do not want your trade to lose. They are indifferent to
where price goes — provided they can hedge.

This one fact explains nearly everything downstream: why prices pin to strikes,
why markets drift on no news, why volatility collapses after an event, and why
"the market makers hunted my stop" is usually a misreading of a mechanical
hedging flow that had nothing to do with you.

## The ecosystem

| Layer | Who | What they want |
|---|---|---|
| Retail | Individuals, small accounts | Direction, lottery tickets, income |
| Asset managers | Pensions, mutual funds, insurers | Tail protection, yield enhancement, vol suppression |
| Hedge funds | Vol arb, macro, stat arb, event | Relative value, convexity, dispersion |
| **Market makers** | Citadel Securities, IMC, Jane Street, Susquehanna, Optiver, Wolverine | Spread capture, flat greeks |
| Exchanges | CBOE, Nasdaq PHLX, NYSE Arca, MIAX, BOX | Volume and listing fees |

Concentration is extreme. In the US retail options segment (April 2025), Citadel
Securities executed ~34% of routed contracts, IMC ~25%, and Jane Street ~13% —
roughly three quarters of retail option flow through three firms. Across
equities more broadly, the top five liquidity providers account for around 70%
of volume.

That concentration is *why* dealer positioning is a usable signal at all. If
hedging flow were spread across thousands of independent participants it would
cancel out. Instead it aggregates into a small number of books that all have to
hedge the same way at the same time.

## How a market maker actually makes money

1. **Sell the spread.** Quote a bid and an ask, capture the difference. On a
   $10.00 / $9.20 market that is $80 per contract round trip, and they do it
   millions of times.
2. **Hedge the delta immediately.** Sell a call, buy shares. The directional
   risk is neutralised within seconds.
3. **Manage the residual greeks.** Gamma, vega and theta cannot be hedged away
   with stock alone. Gamma is hedged by continuous rebalancing; vega is hedged
   with other options; theta is what they collect for holding the book.
4. **Earn the volatility risk premium.** Structurally, customers pay above fair
   value for protection. Dealers are net sellers of that protection and get paid
   the difference between implied and realized volatility.

The critical consequence: **step 2 forces them to trade the underlying, and the
size of that trading is dictated by their gamma.** That is the mechanism behind
everything in the daily report.

## Payment for order flow and why retail flow is valuable

Wholesalers pay retail brokers for the right to execute their orders — $841
million across 1.97 billion contracts in a single month (April 2025). They pay
because retail option flow is **uninformed and predictable**: small size, mostly
buying premium, heavily weighted to short-dated OTM strikes. That is exactly the
flow you want to be on the other side of.

Institutional flow is the opposite: large, informed, and often the reason a
market maker gets run over. Dealers price accordingly, which is part of why the
surface has skew at all.

## The scale, and why it feeds back into the stock market

US options notional volume now exceeds the combined notional of the cash equity,
equity futures and ETF markets. When an instrument that large requires
continuous delta hedging in the underlying, **the tail wags the dog.** Option
positioning is no longer a derivative of the stock market; on many days it is a
driver of it.

This is the honest version of "institutional manipulation". It is not a
conspiracy and there is rarely intent. It is thousands of hedging obligations
executing simultaneously because the math requires it. But the effect on price is
real, it is large, and — crucially — **it is computable in advance from open
interest**, which is public.

That is the entire premise of this system.

## Where the retail trader is structurally disadvantaged

- **Spread.** Every market order pays it. On illiquid strikes it can exceed the
  edge in the trade.
- **Information about flow.** Dealers see order flow; you see prices.
- **Speed of hedging.** They rebalance continuously; you cannot.
- **Vol pricing.** They know where the surface should be; retail buys whatever
  is quoted.

## Where the retail trader is structurally advantaged

- **No mandate.** You can sit in cash for a month. A market maker must quote.
- **No capacity constraint.** Strategies too small for a fund are fine for you.
- **No forced hedging.** You are never obligated to buy a rally you hate.
- **Public positioning data.** Open interest is free. Most retail ignores it.

The realistic edge for an individual is not out-trading Citadel on price. It is
**knowing which regime the mechanics have put the market into, and choosing
structures that get paid in that regime.**

---

**See also:** [02-expiration-mechanics.md](02-expiration-mechanics.md) ·
[03-dealer-flows.md](03-dealer-flows.md) · [06-players-and-edge.md](06-players-and-edge.md)
