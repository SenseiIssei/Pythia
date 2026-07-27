# Breakthrough plan — new algorithms, and an app anyone can use

> Sits between [`../PROFIT-PLAN.md`](../PROFIT-PLAN.md) (where an edge could come
> from) and [`FORECASTING.md`](FORECASTING.md) (how the current forecaster works).
> This document is about the next step change in both halves of the product: the
> algorithms, and who can actually operate them.

Two bets, and they are the same bet twice.

**Bet 1 — the edge is in aggregation and cost, not in prediction.** Almost every
competitor is trying to predict better. That is the hardest possible place to
compete and the one where retail loses to institutions on data, latency and
capital. The tractable edges are elsewhere: combining sources that disagree,
knowing which ones have earned trust, and not giving the result back in fees.

**Bet 2 — the moat is comprehensibility.** Every trading bot on the market is
built for people who already trade. That is a small, saturated, sceptical
audience. The much larger group is people who *want* exposure to this and are
correctly frightened of tools they cannot read. Being the one they can read is
worth more than one more indicator.

---

## Part I — Algorithms

Five, ordered by expected value per week of work. Each has a falsification test,
because an algorithm without one is a belief.

### 1 · Hierarchical calibration with partial pooling — *highest value, ~1 week*

**The problem this solves.** The current [`trust`](../crates/pythia-core/src/forecast/calibration.rs)
needs ~50 resolved forecasts before a source counts for anything. That is
correct, and it is also brutal: a new provider is mute for weeks, and a source
that is excellent on crypto but useless on politics gets one averaged number
that describes neither.

**The algorithm.** Model calibration as a hierarchy — a global prior over "how
well do forecasters do", a per-source level, and a per-source-per-category level
— and shrink each level toward its parent by how much data it has. This is
standard multilevel modelling, and it is the right tool the moment you have many
sources × many categories with unequal evidence.

```
skill(source, category) = w₁·global + w₂·source + w₃·(source × category)
   where wᵢ ∝ evidence at that level
```

**Why it is a breakthrough here and not just a refinement.** It turns the cold
start from a wall into a ramp. A new model inherits the global prior — "language
models are roughly this calibrated on roughly this kind of question" — instead of
starting at zero. And it lets the app say something no competitor can: *"Claude
is good at macro questions and no better than the market on crypto."* That is a
sentence with a number behind it.

**Falsification:** hold out 20% of resolved forecasts. If the hierarchical
estimator does not beat the current flat one in out-of-sample log loss,
especially for sources with n < 50, it is complexity for nothing.

### 2 · Copula-aware ensemble weighting — *~1 week*

**The problem.** [`effective_n`](../crates/pythia-core/src/forecast/aggregate.rs)
already reports that five agreeing models are not five pieces of evidence — but
only reports it. The pool still treats them as independent, which systematically
overweights whichever view the training data happened to favour.

**The algorithm.** Estimate the correlation matrix of source *errors* (not their
forecasts) from the resolved history. Down-weight clusters:

```
w_effective = w_measured · (1 / Σⱼ ρᵢⱼ)
```

Two models whose errors correlate at 0.9 should together count for barely more
than one. A statistical source whose errors are *uncorrelated* with the language
models should count for far more than its solo skill implies — it is adding an
independent dimension, which is exactly what an ensemble is for.

**Why it matters more than it sounds.** It changes what is worth paying for. If
GPT and Claude have 0.85 error correlation on event questions, the second
subscription is buying almost nothing, and the app can say so. If a cheap
statistical source decorrelates the pool, it is worth more than a frontier model.
Nobody in this space measures that.

**Falsification:** compare pooled Brier with and without the correlation
adjustment on held-out data.

### 3 · Adaptive execution as a bandit — *~2 weeks, the surest payoff*

**The problem.** `PROFIT-PLAN.md` §4 established that execution is the only
guaranteed alpha. The engine still emits market orders exclusively.

**The algorithm.** Treat "how aggressively do I cross the spread" as a contextual
bandit. Arms: post-only at mid, join the touch, cross. Context: spread, top-of-
book depth, hour of session, realised volatility, signal urgency. Reward: realised
slippage against the arrival price, minus a penalty for not filling.

Thompson sampling over these arms, per venue, learns the venue's microstructure
from your own fills — which is data you already generate and currently throw away.

**Why it is the surest.** It does not require being right about the market. Ten
basis points saved on a strategy doing 20 round trips a month is 24 points a
year, and unlike a forecast it does not depend on anyone's opinion. The
[order state machine](../crates/pythia-core/src/connectors/mod.rs) built for the
live-execution work — submit → poll → cancel — is exactly the substrate this
needs, and it already exists.

**Falsification:** A/B against always-cross for 200 fills. Median realised
slippage must drop. This one is nearly certain to work; the risk is only in
magnitude.

### 4 · Cross-venue statistical arbitrage with inventory control — *~3 weeks*

**The opportunity.** Pythia now speaks to Kraken, Binance, Bybit, OKX and Alpaca
simultaneously. Practically no retail tool does. The spread between BTC/USDT on
one venue and BTC/USD on another is a *market-neutral* series — trading it
requires no directional forecast at all, which removes the hardest part.

**The algorithm.** An Ornstein–Uhlenbeck model of the spread — estimate the
mean-reversion rate θ and volatility σ, enter at ±kσ, size by half-life so
capital is not parked in a spread that takes a week to close. Inventory control
caps net exposure per asset so a persistent dislocation (a venue in trouble) does
not become an unbounded position.

**The honest caveat.** This is the one item here that may simply not exist at
retail size. That is why step one is not to build it but to **watch it**: log the
spread for 30 days and see whether it ever exceeds round-trip costs. Answer in a
month, at zero risk, for a few hours of work.

### 5 · LLM as extractor, statistics as forecaster — *~2 weeks*

**The problem.** Asking a model for a probability asks it to do arithmetic it is
bad at, in a domain where it cannot check itself.

**The algorithm.** Split the job. The model does what language models are
genuinely superhuman at — reading a filing, a rules page, a news item, and
emitting *structured facts*: has the condition already been met, what is the
resolution criterion exactly, is this news material or noise, does this event
depend on another market Pythia already prices. Those facts feed a small logistic
model whose coefficients are fitted on resolved history.

**Why the split wins.** Language to the language model, probability to the
statistics. The extraction step is verifiable — you can check whether it read the
resolution date correctly — where "0.73" is not.

**A concrete first win:** many Polymarket questions are *conditionally related*
("Fed cuts in July" vs "Fed cuts before September"). Logical implication between
them is a hard constraint — P(July) ≤ P(before September) — and violations are
arbitrage in the same model-free sense as
[coherence](../crates/pythia-core/src/forecast/coherence.rs). An LLM is excellent
at spotting that two questions are nested. The arithmetic that follows needs no
model at all.

### Sequencing

Weeks 1–2 (1, 2) improve every forecast already being made and need no new
infrastructure. Weeks 3–4 (3) is the surest money. Week 5 (4, observation only)
is a cheap lottery ticket on a real structural advantage. Weeks 6–7 (5) is the
highest ceiling and the highest variance.

---

## Part II — An app anyone can use

### The principle

> **If a beginner cannot act on a number, it does not belong in the default view.**

Numbers you cannot influence are not information, they are anxiety. A newcomer
seeing "Sharpe 0.31 · max DD 4.2% · gross exposure $41,200" learns nothing and
concludes the tool is not for them.

### What shipped

**Simple mode is the default** ([`src/uiMode.ts`](../src/uiMode.ts)). Five
destinations — Home, Predictions, Money, Settings, About — against eighteen in
advanced. A switch at the top of Settings, and a link in the Home explainer.

**A Home page that answers four questions, in order of how much they matter:**

1. *Is my real money at risk?* An unmissable banner. Green "Practice mode — no
   real money" or a pulsing red "This is real money".
2. *How am I doing?* One large number and one sentence: "Up $412.30 today
   (+0.41%) · started the day at $100,000".
3. *What is it doing?* Markets watched, strategies running, trades made today,
   things it owns.
4. *What does it think?* The three strongest views, in sentences: *"Everyone else
   says 53% likely. Pythia says 61%. It thinks that is 8 points too low."*

Plus a large stop button that explains what stopping does, and a collapsible
"What is this app actually doing?" that covers practice mode, why it has to earn
trust, and that nobody can promise profit.

**Vocabulary, deleted.** P&L → "up/down today". Equity → "what your account is
worth". Drawdown → "worst dip". Basis points → percentages, or gone. Kelly,
Brier, log-odds, gross exposure → advanced only. `llm:anthropic` → "Claude".
`stat:longshot` → "The long-shot rule".

**Refusals in plain words.** The forecaster's reasons are translated, not hidden:
`edge 180bps does not cover the 300bps round-trip cost` becomes *"The difference
is smaller than the fees it would pay to trade it."*

**What simple mode never hides.** The mode banner, the kill switch, any warning
about real money, and the fact that a position was bought for real. Hiding risk
to look friendly would be the one unforgivable version of this feature.

### What is next

- **A first-run walkthrough.** Four screens: this is practice money · here is
  what it is doing · here is the stop button · here is how you would go live, and
  why you should not yet.
- **Plain-language explanations everywhere.** Every number gets a one-sentence
  hover: "Worst dip — the biggest fall from a high point. Smaller is calmer."
- **Goal-shaped setup instead of parameter-shaped.** Ask "how much are you
  willing to lose in a bad month?" and derive the risk limits from the answer,
  rather than asking for `maxDailyLossPct`.
- **A weekly plain-English report.** "This week Pythia made 14 trades, was right
  on 8, and finished up $212. Its predictions have now been checked 340 times and
  are still not beating the market, so it is not betting on them."
- **Recoverable mistakes.** Every destructive action needs a plain confirmation
  that says what will happen in words, and an undo where physics allows one.

### The metric

Not engagement. **Can a person who has never traded, given the app and no
explanation, correctly answer these three questions within two minutes?**

1. Is real money at risk right now?
2. Am I up or down today, and by how much?
3. How do I make it stop?

If any answer takes longer than that, the default view has failed, regardless of
how good the algorithms underneath it are.

---

## The connection between the two halves

They are not separate projects. The forecasting layer's core property — *a source
must earn trust before it can move money* — is the same property that makes the
app safe to hand to a beginner. Nothing acts on an unproven opinion. The
scoreboard is both the research instrument and the honesty mechanism.

An app that says *"it is still learning, so it is mostly agreeing with the market
on purpose"* is simultaneously the most rigorous and the most beginner-friendly
thing on the market. That is the whole thesis.
