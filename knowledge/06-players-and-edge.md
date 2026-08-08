# 6. The players: who is good at this, and what they actually do

Useful less as hero worship than as a map of *the distinct kinds of edge that
exist in options*. There are only a handful, and every serious participant is
running some version of one of them.

## The market makers — edge from flow and speed

These are the firms on the other side of most retail trades. They are not
directional. Their edge is spread capture at scale plus superior vol pricing.

| Firm | Note |
|---|---|
| **Citadel Securities** | Largest US retail options executor (~34% of routed retail contracts, Apr 2025). |
| **IMC Trading** | ~25% of retail options flow — larger than Susquehanna and Wolverine combined. |
| **Jane Street** | ~13% of retail options; dominant in ETF creation/redemption arbitrage. |
| **Susquehanna (SIG)** | Founded by **Jeff Yass**. Built explicitly on probability and game theory — famously recruits poker players. Among the deepest options-pricing cultures in the industry. |
| **Optiver** | Amsterdam-founded; ~$3.8bn trading revenue in 2024. |
| **Wolverine, GTS, Virtu** | Significant remaining share. |

Top three firms account for roughly half of total volume; top five for ~70%.

**The edge:** thousands of small, uncorrelated spread captures per day, hedged
continuously. Not replicable by an individual — but understanding *how they must
hedge* is exactly what makes dealer-positioning analysis work.

## The volatility specialists — edge from the surface

**Nassim Nicholas Taleb.** Made his name on convexity: buy cheap far-OTM options,
lose small repeatedly, win enormously in the rare dislocation. Profited from Black
Monday 1987 and 2008. The intellectual foundation of the tail-hedge business.
His core insight is not "buy puts" — it is that **the market systematically
misprices the tails because the lognormal model has no room for them.**

**Universa (Mark Spitznagel).** The institutional implementation of that idea: a
dedicated tail-risk overlay designed to lose a small amount almost always and
pay off violently in crashes.

**The other side of the same trade** is the systematic premium seller, harvesting
the volatility risk premium — the structural fact that IV exceeds RV on average
because institutions overpay for protection. Both sides are legitimate. They
simply take opposite ends of the same statistical fact.

## The quantitative traders — edge from statistics

**Jim Simons / Renaissance Technologies.** The Medallion fund generated over
$100bn in trading profits between 1988 and 2018. Not an options shop
specifically, but the definitive proof that systematic statistical edge, applied
with discipline and enormous compute, beats discretionary judgment over time.

**Jeff Yass (Susquehanna).** Built the firm on applied probability. The relevant
lesson: options are a *probability pricing* business before they are a *direction*
business.

## The macro discretionary traders — edge from asymmetry

**Paul Tudor Jones.** Famous for 1987, but the durable lesson is his use of
options for **asymmetric expression**: risk a defined premium to express a macro
view, rather than a leveraged linear position with a stop that can be gapped
through.

**John Arnold.** Natural gas — made ~$750m in a single year. Edge came from deep
fundamental knowledge of a specific market's physical supply/demand plus options
to express it with convexity.

## The educators / platform builders

**Tom Sosnoff.** Founded thinkorswim and later tastytrade. His contribution is
less a trading edge than the mainstreaming of a systematic, mechanical,
premium-selling framework with explicit rules — high IV rank entries, ~45 DTE,
managing winners early. Worth knowing because a large share of retail behaviour
now follows this template, which itself shapes flow.

## The five kinds of edge — the actual taxonomy

Everything above reduces to one of these:

1. **Flow / speed edge.** See order flow first, hedge fastest. Market makers.
   *Not available to individuals.*
2. **Structural / risk-premium edge.** Get paid to hold risk others must shed —
   the VRP. Systematic premium sellers. *Available, but requires surviving the
   tails.*
3. **Convexity edge.** Own the mispriced tail. Taleb, Universa. *Available, but
   requires tolerating long losing stretches.*
4. **Informational / fundamental edge.** Know the physical market better. Arnold.
   *Available in narrow niches only.*
5. **Statistical / modelling edge.** Better models, more data. RenTec.
   *Requires infrastructure.*

**The realistic path for an individual is a disciplined version of #2 and #3,
gated by regime.** Sell premium only when the mechanics AND the VRP both say you
are being paid; own convexity when it is cheap. That is precisely what the daily
report is built to determine.

## What this system is not

It does not give you a market maker's flow edge, and it will not turn a retail
account into Renaissance. What it does is make the **positioning layer** visible
— the layer that most retail traders never look at and that determines whether
your strategy is being paid or being harvested this week.

---

**See also:** [01-market-structure.md](01-market-structure.md) · [07-daily-playbook.md](07-daily-playbook.md)
