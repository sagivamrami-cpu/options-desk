# 10. Reading options flow

Flow is the tape of the options market: who traded, at what size, and against
which side of the quote. Services like OptionStrat Flow, and the unusual-activity
scanners generally, all sell the same underlying data with different filters.

Used well it tells you what large participants are *doing*. Used badly — which
is the norm — it tells you a story you invented about a trade whose other three
legs you could not see.

## The vocabulary

**Sweep.** One order split across multiple exchanges simultaneously to fill
immediately. The defining feature is urgency: the buyer accepted worse prices
across venues rather than wait. Sweeps are the closest thing to a genuine
signal in flow data, because paying up is a choice that costs money.

**Block.** A single large print, usually negotiated off-exchange. Size without
urgency. Frequently one leg of something larger, or a hedge against a position
you cannot see.

**At the bid / at the ask.** The convention: trades printing at the ask are
inferred as buys, at the bid as sells. It is an inference, not a fact — and it
inverts completely if the counterparty was the initiator.

**Opening vs closing.** The one that actually matters, and the one most often
ignored. Compare the print size against the strike's existing open interest, and
check whether OI rose the next morning. A large print that does not increase OI
closed a position; reading it as a new bullish bet is backwards.

## What flow cannot tell you

**You are usually seeing one leg.** A large call purchase might be: outright
bullish speculation, the long leg of a spread whose short leg printed
separately, a hedge against short stock, a covered-call unwind, or the delta
hedge for a structured product. These have opposite implications and identical
prints.

**Direction is inferred, not observed.** The exchange does not publish who
initiated.

**Institutions hedge more than they speculate.** A fund buying $40m of puts is
more likely protecting a much larger long book than predicting a crash. That is
the JPMorgan collar in `knowledge/01-market-structure.md`: enormous, entirely
mechanical, and meaningless as a directional signal.

**Survivorship in the retelling.** Nobody posts the sweep that expired
worthless. The genre selects for the ones that worked.

## What it is genuinely good for

1. **Confirming positioning you already inferred.** If GEX says a strike is a
   wall and flow shows repeated size printing there, that is two independent
   readings agreeing. This is the best use.
2. **Spotting a regime change early.** A sustained shift from call to put
   buying across strikes and expiries, especially in sweeps, is real
   information about demand for protection.
3. **Finding the event nobody told you about.** Unusual activity concentrated
   in one name and one expiry often precedes news. Note it is *concentrated*
   that matters, not large.
4. **Understanding tomorrow's dealer position.** Today's flow becomes tomorrow's
   open interest, which becomes the gamma profile this whole system reads.

That last point is the connection worth internalising. **Flow is the derivative
of positioning.** GEX, the flip level and max pain are computed from open
interest, which is the accumulated result of flow. Watching flow is watching
the gamma profile being built before it appears in the data.

## Integrating it with this system

The two are complementary, not competing:

| | This system | Flow services |
|---|---|---|
| Answers | how the market is *positioned* | what is being *traded now* |
| Source | open interest, quoted surface | the trade tape |
| Update | once a day (OI) | real time |
| Strength | mechanics, levels, distributions | urgency, size, early warning |

A sensible workflow: read the positioning first (it changes slowly and sets the
regime), then use flow to see whether today's activity is reinforcing or
attacking that structure.

OptionStrat exposes an API on its Live Flow tier. The data layer here is
deliberately modular — `optionsdesk/sources/` — so a flow adapter drops in the
same way the IBKR one did, without touching anything downstream.

## The discipline

Before acting on any flow observation, answer three questions:

1. **Opening or closing?** Check open interest tomorrow. If you cannot tell,
   you do not know what the trade means.
2. **Is this a leg or a position?** Look for offsetting prints in the same name,
   same timestamp, adjacent strikes or expiries.
3. **Speculation or hedge?** What else does this participant likely own? Size
   relative to the underlying's normal volume is a clue; size relative to your
   imagination is not.

If all three are unanswerable, the print is noise with a large number attached.
Most of them are.
