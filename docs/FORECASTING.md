# Forecasting — how Pythia predicts, and why you can check it

> The Predictions page, end to end. Read [`../SAFETY.md`](../SAFETY.md) first, and
> [`../PROFIT-PLAN.md`](../PROFIT-PLAN.md) for where an edge could actually come from.

Most "AI trading" is a language model asked *will this go up?*, answering in a
confident paragraph, with a number bolted onto the end. Nobody scores it, so
nobody finds out it was a coin flip with good prose.

Pythia is built the other way round. The number is recorded before reality
arrives, scored against what happened, and compared against the market's own
forecast on **the same questions**. That score — not the eloquence, not the
model's self-reported confidence — is the only thing that decides how much a
source is allowed to move an order.

---

## 1 · The pipeline

```
market price ───────────────────────────────────────────┐  (the default answer)
stat:longshot ─┐                                        │
stat:momentum ─┤                                        ▼
stat:drift    ─┼─► recalibrate ─► weight by ─────► pool ──► shrink toward ──► ensemble
llm:anthropic ─┤    (learned)     track record   (log-odds)     market           │
llm:openai    ─┤                                                                 ▼
llm:…         ─┘                                              edge − costs ──► Kelly ──► action
```

Every stage is a place where an unjustified opinion gets quieter.

### Sources

| Source | Question it answers | Hypothesis |
|---|---|---|
| `market` | — | The price. The baseline every source must beat. |
| `stat:longshot` | event | Favourite–longshot bias: longshots trade rich, favourites cheap. Stretches log-odds by `k`. |
| `stat:momentum` | event | Odds drift continues, weakly, damped as resolution approaches. |
| `stat:drift` | directional | `Φ(μH / σ√H)` with the drift shrunk hard — because an estimated drift on 200 bars is mostly noise. |
| `llm:<provider>` | both | A calibrated forecaster following the reference-class protocol below. |

They are separate named sources on purpose. When the scoreboard says
`stat:longshot` has skill and `stat:momentum` does not, you have learned
something specific and can delete the one that does not work.

### Pooling

In **log-odds**, never in probability. Averaging 0.02 and 0.20 linearly gives
0.11; in log-odds it gives 0.063, which is the answer that respects the odds
ratio. Weights come from the scoreboard.

Extremizing (pushing a consensus further from 0.5) is available but **off by
default**. It is the correct correction for independent forecasters; a pool of
large language models trained on overlapping data is nowhere near independent,
and five of them agreeing is closer to one of them saying it five times. The
`Effective sources` gauge on the page is Kish's effective sample size and shows
exactly that.

### Shrinking

The pooled view is then pulled back toward the market price. How far it is
allowed to stay away is `trust`, which saturates in the total weight of the
sources. One unproven source barely moves it. Five proven ones move it a lot —
never all the way.

---

## 2 · What earns weight

```
BSS = 1 − brier(source) / brier(market)      # skill, on the same questions
trust = clamp(BSS, 0, 1) × n / (n + 50)      # discounted by how little evidence there is
```

Both factors have to be present:

- **Skill** — a Brier score of 0.18 sounds good until you learn the market
  scored 0.16 on the same questions. Beating 0.5-every-time is not an
  achievement; beating the market is.
- **Evidence** — five good calls is luck. At n = 50 a perfect source is trusted
  at 0.5; at n = 200, 0.8.

A source that cannot beat the market gets **exactly zero**, and zero weight
means it cannot move a single order no matter what it says.

Each source also gets a learned **recalibration** — `p' = logistic(a·logit(p) + b)`
fitted on its own record once it has 30+ resolved forecasts. A model that says
0.95 for things that happen 70% of the time has its extremes pulled in
automatically. The page shows both numbers: *"said 95.0%, recalibrated"*.

### Where the scoring data comes from

Election markets settle in months, which would mean no calibration data for a
very long time and every source stuck at zero forever. So two kinds of forecast
are recorded:

| Kind | Question | Resolves |
|---|---|---|
| `outcome` | Will the event happen? | When it settles |
| `direction` | Will this price be higher after the horizon? | On a timer, every horizon |

For an event market the directional view is *derived* from the level view —
`logistic(logit(model) − logit(market))`, which is 0.5 when they agree and moves
monotonically with the edge. It is a real, falsifiable forecast that resolves in
an hour instead of in November.

Scores are kept **separately per question type**. Being right about an hourly
tick is not being right about an election, and the code will not let one earn
weight for the other.

---

## 3 · The model protocol

`llm.rs` asks for the steps in this order, and the JSON schema lists them in this
order so structured decoding commits to each before the next:

1. **Reference class** — what class of events is this, and how often do they
   happen? This is `baseRate`, and it comes **first**, before any case-specific
   reasoning. Asking for the answer first gets an inside-view narrative with a
   number attached; asking for the base rate first anchors it to something.
2. **Key drivers** — at most three things the outcome hinges on.
3. **Evidence for AND against**, symmetrically. A model that can only find
   evidence for one side has not looked at the other.
4. **Adjust** from the base rate only as far as step 3 justifies.

The market price is given as an explicit anchor, with instructions that
deviating from it is a *claim*. "The market says 0.60 and I have nothing to add"
is a correct answer, and the prompt says so.

Every provider is asked **concurrently and independently** — none sees another's
answer. Feeding one model's output to the next produces agreement, not accuracy.
One provider failing (no key, rate limit, bad JSON) never fails the batch; its
error is shown next to the others' answers.

> Self-reported `confidence` is displayed and **never used as a weight**. It is
> uncorrelated with being right.

---

## 4 · Coherence — the part that needs no forecast

Everything above tries to be *smarter* than the market, which is hard. Coherence
asks whether the market is consistent with **itself**: the outcomes of one event
are mutually exclusive and exhaustive, so they must price to 1.

When they sum to 0.96, buying every outcome costs 96 cents and pays exactly one
dollar whatever happens. No opinion about the world is involved.

Breaks are reported **net of costs**, with the cost scaling by the number of
legs — which is why three- and four-way events rarely pay even when the raw gap
looks generous. A break that does not clear costs is shown as a near-miss rather
than hidden, because those are the data that tell you whether the opportunity
exists at your size at all.

---

## 5 · From forecast to order

```
edge      = ensemble − market
net edge  = |edge| × 10000 − costBps
action    = Buy / Sell   if net edge > minEdgeBps
            Hold         otherwise, with the reason
kelly     = (p − price) / (1 − price) × kellyFraction
```

A prediction-market signal from the Prob-Edge strategy is **dropped** unless its
market's forecast clears costs. The strategy's own threshold is about the signal;
this gate is about the cost of acting on it, and both have to pass.

Every `Hold` carries a specific refusal, not a shrug:

- `no source has earned any weight yet — forecasts are being recorded and scored,
  but none may move an order until it beats the market on its own track record`
- `edge 180bps does not cover the 300bps round-trip cost`
- `net edge 40bps is below the 100bps minimum`

---

## 6 · Using it

**Predictions page.** Every market, sorted by net edge. Expand one to see each
source's number, its weight, its track record, and what it said. Below that, the
scoreboard: Brier, the market's Brier on the same questions, skill, bias, trust.

**Ask the model ensemble** runs one API call per configured provider for that
market. It is never automatic in the UI — it is the expensive operation in the
app. Optional context in the box at the top is passed verbatim and identically
to every model.

On a server, an automatic sweep is available but **off by default**:

```bash
PYTHIA_FORECAST_SWEEP_MIN=60        # 0 or unset = off
PYTHIA_FORECAST_SWEEP_MARKETS=3     # markets per sweep — this is the spend knob
```

### What you should expect on day one

Nothing. Every source shows `unproven`, trust is ~0, the ensemble sits on the
market price, and every action is `Hold`. That is the design working: forecasts
are accruing and being scored, and none of them has yet earned the right to
disagree with a market.

If you want it to act sooner, `bootstrapTrust` (default `0.10`) is the weight an
unproven source gets. At 0.10 an untested model saying 95% against a market at
50% moves the ensemble to roughly 55% — a nudge, not a shout. Set it to `0` for
strict mode, where nothing untested counts at all.

---

## 7 · What this is not

It is **not** a claim that any of these sources has an edge. It is the machinery
that will tell you, with a number, within a few hundred resolved forecasts,
whether one does — and keep it silent until then.

If after a real track record every source sits at zero skill, that is a genuine
and useful result: it means the market was efficient on those questions, and the
correct response is to stop paying for API calls, not to lower the bar.
