# 4. The volatility surface

An option's price is a price *of volatility*. Two options on the same underlying
with different strikes and expiries trade at different implied vols. That
three-dimensional object — IV as a function of strike and time — is the surface,
and reading it is the core skill of an options trader.

## Implied vs realized volatility

| | Definition | What it tells you |
|---|---|---|
| **IV** | The vol input that makes the model price equal the market price | What the market *expects* / is willing to pay |
| **RV** | Annualised standard deviation of actual log returns | What actually *happened* |

`RV = std(log returns over N days) × √252`

**The volatility risk premium (VRP) = IV − RV.**

Structurally positive on average, across essentially every liquid market, and
that is the deepest edge in options. The reason is demand-driven: institutions
systematically buy downside protection they mostly do not need, because tail risk
would destroy them once. That persistent hedging demand keeps IV above RV.

**But it is not always positive.** When VRP turns negative — realized moves
outrunning what options price — premium selling is being *underpaid for the risk
it is carrying*. Selling into negative VRP is how systematically profitable
strategies produce sudden catastrophic quarters. Check it before every short-
premium trade.

## Skew

At the same distance from at-the-money, OTM puts trade at higher IV than OTM
calls in equity products. Almost always. The standard measure is the
**25-delta risk reversal**:

```
skew = IV(25Δ put) − IV(25Δ call)
```

For SPY the 25Δ put typically trades 4–6 vol points above the 25Δ call.

### Why skew exists
- Persistent institutional demand for crash protection.
- Equity markets fall faster than they rise; vol and price are negatively
  correlated, so a lower spot really does imply higher vol.
- Leverage effect: falling equity raises a firm's debt-to-equity ratio.

### How to read the level
- **Steepening** → hedging demand accelerating, fear building.
- **Extremely steep** → often *contrarian*. Fear is peaking and puts are
  expensive to own but attractive to sell (with defined risk).
- **Flat** → complacency, or genuine upside chase.

> **Critical caveat.** Skew reflects *positioning*, not *prediction*. Heavy put
> demand does not mean the market will fall. It regularly means the opposite,
> because that hedging is exactly the fuel for a vanna rally when vol subsides.

### Gold is different — and this matters for GLD

Equity skew is reliably put-heavy. **Gold frequently exhibits flat or even
inverted (call-heavy) skew**, because gold is itself a crisis hedge: the fear
trade in gold is *missing an upside spike*, not a crash. When GLD shows negative
25Δ skew, that is not a data error — it is the market pricing upside convexity.
Do not apply equity-skew intuitions to gold.

## Term structure

ATM IV plotted against days to expiry.

- **Contango (upward sloping)** — near-dated vol cheaper than far-dated. The calm
  default state, roughly 80% of the time.
- **Backwardation (inverted)** — near-dated vol bid *above* far-dated. The market
  is paying up for immediate protection. **This is a stress signature.**

Inversion is one of the highest-quality warning signals available. It is the
condition under which short-premium books break, because it means the market is
pricing an imminent event rather than a diffuse risk.

Term structure also creates the calendar spread trade: sell the rich near-dated
vol, buy the cheaper far-dated, and profit if the structure normalises.

## Smile and the strike dimension

Across strikes at a single expiry, IV typically forms a smile or smirk rather
than a flat line. The wings are bid because the lognormal assumption in
Black-Scholes understates real tail probability. Every liquid market has fatter
tails than the model — the smile is the market correcting for the model's known
defect.

## IV Rank and IV Percentile

Absolute IV is close to meaningless without context. 25% IV is cheap for the
Nasdaq and expensive for a utility.

```
IV Rank       = (IV − IV_min_1y) / (IV_max_1y − IV_min_1y) × 100
IV Percentile = % of days in the last year IV was BELOW today's
```

IV Percentile is generally more robust — a single spike distorts IV Rank badly.

The standard heuristic:
- **IV Rank > 50** → premium is expensive → structures that are net short vega
- **IV Rank < 30** → premium is cheap → structures that are net long vega

Both require a year of daily IV history. This system accumulates that history
from day one and honestly reports "still building" until enough observations
exist, rather than quoting a fake rank from a handful of points.

## Expected move

Two independent readings, which usefully disagree:

```
sigma move   = S × IV × √T                (the model's 1 standard deviation)
straddle     = ATM call mid + ATM put mid (what you would actually pay)
```

When the straddle implies a larger move than sigma, the surface is pricing a fat
tail that the lognormal model does not capture. That gap is itself information.

## Putting the surface together

The surface is a map of **where fear is priced**. Reading it as a whole:

| Observation | Interpretation |
|---|---|
| Low IV rank + flat skew + contango | Complacency. Protection is cheap. Own convexity. |
| High IV rank + steep skew + inversion | Panic. Protection is expensive. Sell it *only* with defined risk. |
| Low IV rank + steep skew | Someone specific is hedging something specific. Pay attention. |
| High IV rank + flat skew | Broad uncertainty without a directional fear. Straddle/strangle territory. |
| Negative VRP in any configuration | Stop selling naked premium. You are not being paid. |

---

**See also:** [03-dealer-flows.md](03-dealer-flows.md) · [05-strategies.md](05-strategies.md)
