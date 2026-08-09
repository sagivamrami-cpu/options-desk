# 8. What the model assumes, and where it breaks

Black-Scholes is not a theory of what options are worth. It is a **translation
device**: it converts a price into a volatility so two options with different
strikes and expiries can be compared. Natenberg's framing is the useful one —
the model is a common language, not an oracle.

Everything below is the list of places the translation leaks. Knowing them is
most of what separates someone who uses the greeks from someone who is used by
them.

## The five assumptions and their real-world failure

**1. Returns are lognormal with constant volatility.**
They are not, in two separate ways. Volatility clusters — calm follows calm and
violence follows violence — and returns have fat tails. This is why a smile
exists at all: the market prices the wings above what the model says, precisely
because it does not believe the model's tails.

*Consequence:* any probability the model hands you is a probability under an
assumption you know to be false. The implied probability of a 5% move is a
price, not a forecast.

**2. Volatility is a single number.**
There is no such thing as "the" volatility of an underlying. There is a surface:
one vol per strike, per expiry. Quoting "QQQ is at 20 vol" means the ATM 30-day
point and nothing more.

**3. Continuous, costless hedging.**
The derivation assumes you rebalance infinitely often at zero cost. In reality
you rebalance discretely, pay a spread each time, and your realized P&L differs
from the theoretical one by a term that grows with gamma and with how far apart
your hedges are.

*Consequence:* the more gamma you carry, the more your actual result depends on
your hedging discipline rather than on whether you were right about volatility.

**4. No jumps.**
The model assumes price moves continuously. Gaps and overnight moves violate
this outright. A delta hedge does not protect you across a gap; only an option
does.

*Consequence:* short-gamma positions are far more dangerous than their greeks
suggest, because the greeks are local and a gap is not.

**5. Known, constant rates and dividends.**
For short-dated equity options the rate barely matters. The dividend does. See
`implied_forward()` in `surface.py`: assuming zero yield on QQQ, whose
parity-implied carry is near 1%, put every modelled put 27–64 cents under the
market. That single wrong assumption made every short-put structure look
profitable.

## Implied is not a forecast, it is a price

The most common category error in options. Implied volatility is the level at
which the market clears — where sellers are willing to take the risk and buyers
are willing to pay for the protection. It embeds a **risk premium**.

That premium is why implied sits above realized most of the time. It is not the
market being wrong; it is the market charging for the service of absorbing
variance risk. Sinclair's point: the option seller is compensated the way an
insurer is, and the compensation is the gap, not the direction.

So the two questions are different:
- *Is IV high?* → a statement about price. Answerable from the surface.
- *Is IV too high?* → a statement about value. Requires a volatility forecast,
  which is a separate and much harder problem.

## Forecasting volatility, briefly and honestly

Volatility is far more forecastable than direction. That is the whole reason
this discipline exists. But "more forecastable than the least forecastable
thing in finance" is a low bar.

What actually works, in rough order of usefulness:

- **Persistence.** Tomorrow's vol looks like today's. A naive "RV20 continues"
  forecast beats most elaborate models over short horizons.
- **Mean reversion at longer horizons.** Vol is bounded below by zero and does
  not stay extreme. High vol decays; very low vol eventually rises.
- **The term structure already contains a forecast.** The market's own
  expectation is embedded in the curve. Beating it requires information it does
  not have, not a different model of the same data.
- **Known events.** Earnings, FOMC, CPI. These are the one case where you
  genuinely know something about future variance that a time-series model does
  not.

What does not work: reading vol off a price chart, or assuming a level is
"too high" because it looks high relative to a period you remember.

## Where the edge actually is

Three places, and only three:

1. **The variance risk premium.** Structural, documented, and available to
   anyone who can survive its drawdowns. This is what `edge_report()` measures
   by comparing the risk-neutral density to a drift-removed empirical one.
2. **Relative value on the surface.** One strike out of line with its
   neighbours. Real but small, and usually eaten by the spread — which is why
   `edge_after_costs()` exists and why it usually returns nothing.
3. **A genuine informational or structural view.** You know something about
   this underlying, or you can hold a position others must exit.

Notably absent: anything derivable from the greeks alone. The greeks describe
your exposure. They do not create edge. A position with attractive theta is not
thereby profitable — it is merely being paid for a risk it is carrying, and the
question is always whether the payment exceeds the risk.
