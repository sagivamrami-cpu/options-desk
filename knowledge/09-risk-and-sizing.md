# 9. Risk, sizing and why most options accounts die

Options do not usually kill an account through bad analysis. They kill it
through correct analysis applied at the wrong size, or through a position whose
loss distribution the trader never actually looked at.

## Probability of profit is a trap

A 95%-probability structure that loses twenty times its credit when it loses is
a negative-expectancy trade with an excellent win rate. It will produce a long,
comfortable run of green days and then remove all of it plus more.

This is the single most common way retail options accounts are destroyed, and
it is attractive precisely because the equity curve looks superb right up until
it does not.

**Rule: never quote a probability of profit without the maximum loss next to
it.** Every agent in this project is instructed to do this. The scanner puts
`pop_empirical` and `max_loss` in adjacent columns for the same reason.

The number that matters is expectancy:

```
E = P(win) x avg_win  -  P(loss) x avg_loss
```

A 95% structure collecting $30 against a $470 max loss needs a real win rate
above 94% just to break even. The market is not usually mispricing that by much
— which is the point.

## Sizing: think in loss, not in capital

The wrong question is "how much capital does this use". The right one is "what
happens to the account if this reaches max loss, and could that happen to
several positions at once".

Practical constraints that survive contact with reality:

- **Cap the loss per position** at a fixed small fraction of the account. For
  defined-risk structures this is exact and knowable in advance, which is the
  main reason to prefer them.
- **Cap correlated risk.** Five short-put spreads on five tech names is one
  position, not five. In a real drawdown every equity correlation goes to one.
- **Undefined risk needs a different rule entirely.** A naked short strangle has
  no max loss to size against. If you trade them, size on a stress scenario — a
  gap of 3–4 standard deviations — not on the margin requirement, which is
  calibrated to normal conditions and will be revised upward exactly when you
  can least afford it.

On Kelly: the mathematically optimal fraction assumes you know your edge and
your distribution. In options you know neither with precision, and Kelly is
extremely punishing to overestimated edge. Practitioners use a fraction of it —
a quarter or less — and even that presumes your edge estimate is honest.

## The greeks are a risk report, not a strategy

Read a position's greeks as a set of questions:

| Greek | The question it answers | What it costs you |
|---|---|---|
| Delta | how much do I lose per point against me | direction risk |
| Gamma | how fast does that delta get worse | the reason gaps hurt |
| Vega | what happens if the market repricies fear | vol risk |
| Theta | what am I paid, or paying, per day | the rent |

The pairings matter more than the individual numbers:

**Short gamma and short vega together** is the classic blow-up profile. When
the market moves, both work against you simultaneously, and they are correlated
— large moves and rising vol arrive together. Every short-premium structure has
this shape. That is not a reason to avoid them; it is a reason to size them as
though the correlated case is the one that will happen.

**Long gamma, short theta** is the mirror. You bleed every quiet day and get
paid for movement. The failure mode is not a blow-up but attrition: being right
about a move that arrives after your expiry.

## Time is not linear

Theta accelerates into expiry, and gamma accelerates faster. A 45-day position
and a 5-day position with the same delta are entirely different animals. The
5-day one can lose most of its value in an afternoon and there is no time for
it to come back.

This is why 0DTE is not "the same trade, shorter". Managing it requires being
present, and sizing that assumes intraday management is sizing that assumes you
are watching every minute.

## When to close

Decide before you open. Three defensible rules:

1. **A profit target as a fraction of max profit.** Taking 50% of a credit
   spread's maximum early gives up the slowest, riskiest part of the payoff —
   the last portion of theta arrives exactly when gamma risk is highest.
2. **A loss multiple of the credit.** Two or three times the credit received,
   mechanically, no negotiation.
3. **A thesis invalidation.** The level broke, the flip crossed, vol regime
   changed. This is the only one that requires judgment, which is why it should
   be written down in advance.

The rule you will actually break is the second one, because closing a loser
requires admitting the analysis was wrong while the position still has time.
That is precisely when it is cheapest to do.

## Evaluate the process, not the outcome

A profitable trade taken at ten times sensible size was a mistake that happened
to pay. Over a small number of trades, outcome tells you almost nothing about
process — the distribution of options returns is skewed enough that a losing
strategy produces winning months routinely.

Track the inputs: was the edge estimate honest, was the size within the rule,
was the exit the one you decided on in advance. Those are knowable immediately.
Whether you had edge is knowable only over a sample large enough that most
retail traders never reach it.
