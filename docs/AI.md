# The Claude API in Pythia

Pythia's own models come first. The Claude API is a data provider behind a
hard budget, used where it adds something the lab's own code cannot: reading
everything at once and writing it down for the owner. Everything it says is
recorded, and where it makes a claim that can be checked, scored. Nothing it
says sizes, places or vetoes an order, and nothing that calls it can change
an autopilot or a setting.

## What is called, and when

| What | When (UTC) | Model | Size of one call | Expected cost |
|---|---|---|---|---|
| Daily brief (`lab.ai.brief`, jobs.yaml `ai-brief`) | every day 06:20, before the digest | `claude-sonnet-5-5`, effort medium, Batches API | about 7,000 tokens in, 2,000 to 4,000 out (thinking included, at most 8,000) | about $0.02 a day |
| Strategy critic (`lab.ai.critic`, jobs.yaml `ai-critic`) | every day 06:40 | `claude-haiku-5-5`, Batches API, one call per autopilot | about 2,000 tokens in, under 500 out | under $0.01 a day |
| Weekly review (`lab.ai.weekly`, jobs.yaml `ai-weekly`) | Sundays 09:00 | `claude-sonnet-5-5`, effort medium, Batches API | 15,000 to 20,000 in, up to 8,000 out | about $0.05 a week |
| Research director (`lab.ai.director`, jobs.yaml `ai-director`) | Sundays 11:00 | `claude-opus-5-5`, effort high, Batches API | about 65,000 tokens in, 15,000 to 25,000 out (thinking included, at most 32,000) | about $0.35 a week |
| Questions in Telegram (`lab.ai.chat`, container `pythia-ai-chat`) | when the owner asks, at most 40 a day | `claude-sonnet-5-5`, effort medium, direct | about 9,000 tokens of instructions and facts (cached), the question, 500 to 1,500 out | $0.01 to $0.04 a question |
| AI overlay (Signals page) | only while switched on, one market every `PYTHIA_AI_INTERVAL_SEC` (120 s) | `claude-haiku-5-5` unless set otherwise | about 900 tokens in, under 100 out | about $0.09 a day while on |
| One signal, an ensemble forecast, a key test | when asked for in the app | the provider's default (Haiku for Claude) | under 2,000 tokens | well under a cent |

**Expected daily cost per job.** The scheduled jobs together: about $0.10 a
day (brief $0.02, critic under $0.01, director $0.05 and weekly review $0.01
averaged over the week). The questions are what moves the total: 10 a day
are about $0.25, the full 40 about $1.00 to $1.60. With the overlay off,
a heavy day is therefore under $2.00, well inside the daily cap of $12.

That is below the $5 to $8 a day the owner has allowed until about
2026-11-20. These levers raise it where it buys something, each one switch
in `/etc/pythia/alerts.env`, no code change:

| Lever | What it buys | Cost |
|---|---|---|
| `PYTHIA_AI_ASK_PER_DAY=100` | more questions | about $0.03 each |
| `PYTHIA_AI_MODEL_ASK=opus` | deeper answers in the chat | about twice a Sonnet answer |
| `PYTHIA_AI_EFFORT_BRIEF=high` | more thinking before the 7-day calls | about +$0.02 a day |
| `PYTHIA_AI_MODEL_CRITIC=sonnet` | a more careful critic (its score says whether it needs it) | about $0.02 per autopilot a day |
| `PYTHIA_AI_EFFORT_DIRECTOR=max` | the deepest weekly drafts | about +$0.30 a week |

Each job reads `PYTHIA_AI_MODEL_<JOB>` (haiku, sonnet, opus, or a full model
id the engine prices) and `PYTHIA_AI_EFFORT_<JOB>` (low to max) for
`BRIEF`, `CRITIC`, `DIRECTOR`, `ASK`. The ledger records the model that
answered every call, so a change shows in the spend table and in the scores.

**Daily brief.** One request covers every coin. It reads the fact sheet
(`lab.ai.facts.fact_sheet`): daily closes (1, 7 and 30-day returns, 30-day
volatility, distance to the 200-day mean and the one-year high), settled perp
funding, flow and positioning from the flow lake (Deribit DVOL and 25-delta
skew, stablecoin supply, the Coinbase and Upbit premiums against Binance),
every autopilot (running, paused, or stopped in the last 7 days) with its
stop rules, sleeves, fees, drawdown, benchmark and forward status, the
headline and first items of the lab's feeds (forward report, real money
readiness, learning loop, models, factory, flow overlays, listings, trending,
the pump.fun real-time study, memecoins, CS2 and Pokemon movers) and the
pump.fun real-time collector's heartbeat and shadow book. Our own models'
forecasts are not shown to it, so its calls stay independent of what they are
scored against. It answers in a JSON schema: for BTC, ETH and every coin a
running autopilot trades, the probability that the close 7 days after the
latest close is higher, with one line of reason, plus three plain lines that
the daily Telegram digest quotes under "AI brief (shadow)". When the alert
language is German it gives the three lines in German as well (`summaryDe`):
the chat gets the German ones, the app keeps the English ones. The answer is
checked before anything is kept (a coin not asked for, a duplicate, a
probability outside 0 to 1 is dropped and named). It goes to
`reports/ai_brief/latest.json`, which also shows up on the Research page.

**Strategy critic.** For each running or paused autopilot (and any that
stopped in the window), the numbers of its last 24 hours are computed first:
orders, fills, rejects, round trips and side flips per market, what traded,
fees in bps of what traded and of equity, realised against modelled cost, the
equity's low against the stop floor, the drawdown against the trailing rule,
the P&L against the loss rules. Haiku gets those, the rules, the orders and
events and how the markets moved, and answers in a schema: ok, or up to three
findings (churn, fees, stop, sizing, drift, rules, other; low, medium or
high). Each finding is checked against the same numbers: churn is confirmed
by two round trips or three side flips, fees by realised cost 1.5 times the
model or fees of 20 bps of equity in a day, a stop by a breached rule while
the autopilot still runs; the other kinds stay unchecked. Every finding goes
to `<data>/ai/critic.jsonl` with an id (`1020-1`); a Telegram card goes out
only for medium or high ones. The owner settles what the numbers cannot with
`/real 1020-1` or `/notreal 1020-1` in the chat (`<data>/ai/critic_labels.jsonl`,
which wins over the numbers). `reports/ai/critic_score.json` keeps the
score: of the decided findings, how many were real.

**Weekly review.** Reads an excerpt of every study write-up, the headlines of
every lab report, the forward evidence, the autopilots, the brief's own score
and last week's proposals, and proposes the three most promising next
experiments. Written to `reports/ai/weekly.md` (and a dated copy).

**Research director.** Reads the summary of every write-up in `results/`
(the opening, then the summary, verdict and result sections, then the rest,
up to 6,000 characters each), the trial ledger (the pool of trials counted so
far and the noise bar it sets, the factory's best in-sample genomes, every
held-back check), the forward evidence, every autopilot, the lab's
headlines, the brief's and the critic's scores, this week's Sonnet review as
a second opinion and the titles of the drafts already written. It writes
three to five pre-registration drafts, each with question, why now, data,
design, trials (with their count), costs, pass rule, kill rule, effort, what
could fool us and the studies it builds on, to
`research/lab/proposals/<date>-<slug>.md` (on the server
`/opt/pythia-lab/proposals/`, kept by `deploy_lab.sh` like `results/`, with
a copy under `reports/ai/proposals/` that the PC sync brings home), the index
to `reports/ai/director.json` and one Telegram card listing them (category
Studies). Drafts only: the owner, or a run the owner starts, picks one up,
fixes its numbers before any result exists and commits it to `results/` as
the study's pre-registration.

**Questions in Telegram.** The owner asks in the alert chat; only the chat
in `PYTHIA_TELEGRAM_CHAT_ID` is answered. Each question goes to Sonnet with
the fixed instructions and the fact sheet (the brief's, plus today's brief,
its score, the critic's findings, the director's drafts and the Claude spend
of the week) as the cached system prompt, the last three exchanges and the
question. It answers in the language of the question. A message that asks to
trade, to start, stop or change an autopilot, to change a setting or for a
key, token, password, chat id or server detail is refused twice over: by a
plain check before any call (nothing is spent), and by the model, which
answers `refuse_trade` or `refuse_secret` when the check let it through.
Whatever comes back is scrubbed of anything shaped like a key, a bot token
or an IP address. The module itself has no way to act: it reads the state
and the reports and sends text. Every question, its answer, the model and
its cost go to `<data>/ai/chat.jsonl`; refusals and over-limit questions are
logged without a call. The setup is in `research/ops/README.md`, "Questions
in Telegram".

All the scheduled jobs run once per day or ISO week; running one again the
same day or week does nothing unless `--force` is given. `--dry-run` prints
the prompt and its size and calls nothing.

## How it is scored

Every brief call is appended to `<data>/ai/predictions.jsonl` before its week
starts, together with what two references said at the same moment, from the
same daily closes:

- **Base rate**: the coin's share of up weeks over the last year.
- **Momentum rule**: how often a week went up after the 28-day return had the
  sign it has now, over the last two years. The rule the momentum paper books
  trade, as a probability.

Seven days after its reference close a call resolves. `reports/ai/scores.json`
is recomputed from the closes on every run: Brier score, log loss and hit rate
for the LLM and both references, the LLM's Brier difference to each with a t
statistic (the weeks overlap, so the effective sample is divided by seven),
reliability, per coin, per week and per model (the brief moved from Haiku to
Sonnet on 2026-10-20, so each model's calls are also scored on their own).
Below 30 resolved calls the verdict is "too early". The Models page shows it
as **LLM vs our models**, with the latest brief and the weekly review. Run
`python -m lab.ai.score` to rescore without a call.

The critic is scored by `python -m lab.ai.critic --score` (and on every run):
findings, runs, autopilot days checked, real and not real, undecided, the
share real, per kind.

## What it costs, where to see it

- **Settings, Claude API budget** in the app: the three caps, spend against
  each, the last calls, and **Spend per job**, a table of every job's spend
  per day over the last 7 days with its total (`byJobDay` in
  `GET /api/ai/budget`, 14 days of it).
- **The weekly report** on Telegram (Sundays 18:00 Berlin) ends with one line:
  what the Claude API cost that week, the daily average and the jobs, dearest
  first.
- **The ledger** itself, `<data>/ai/ledger.jsonl`, one JSON line per call.

## The budget

Every Claude call in Pythia goes through one gate, in the engine
(`crates/pythia-core/src/ai_budget.rs`):

1. Before anything is sent, the call's worst case (the prompt at two
   characters a token, every allowed output token) is checked against the
   persisted ledger and three caps. If it would cross any of them, the call is
   refused and nothing is sent.
2. The room is held while the call is in flight, so two calls cannot both take
   the last dollar.
3. When the answer is in, the call is appended to `<data>/ai/ledger.jsonl`
   with its tokens (input, output, cache write, cache read), whether it went
   through a batch, the model that answered, and its cost. A refused or
   unreadable answer is billed and recorded too; a batch given up on is
   recorded at its worst case. An HTTP error before an answer is not billed and
   frees the room.

| Cap | Default | Set by the owner (2026-10-20) | Period |
|---|---|---|---|
| Lifetime | $90.00 | $265.00 | every call ever |
| Monthly | $15.00 | $265.00 | the calendar month, UTC |
| Daily | $1.50 | $12.00 | the day, UTC |

The defaults stay low on purpose (a missing or broken `budget.json` falls
back to them); the owner's caps live in `<data>/ai/budget.json`. The largest
single reservation is the director's, about $0.60 at its worst case.

A lab job may ask for at most 32,000 output tokens and send at most 800,000
characters (about 200,000 tokens); the director is the one that needs it.

A Telegram alert goes out when the lifetime spend passes 50 %, 80 % and 100 %
of the lifetime cap, and the first time a call is refused because the lifetime
cap is used up. Each step is sent once (`<data>/ai/alerts.json` remembers
which); the 100 % alert is sent even in quiet hours.

The lab jobs do not call the API themselves. They ask the autopilot engine
(`POST /api/ai/complete`, this machine only) and prove they may by a hash of
the same key, so every paid call has one gate and one ledger. Several engine
processes may share the ledger folder; each reads what the others appended
before every check.

The desktop app keeps its own ledger in its data folder and also counts the
server's ledger when the lab data is synced to the PC, so both stay under one
set of caps.

### Changing the caps

- In the app: **Settings, Claude API budget**. Enter the three amounts and
  save; **Defaults** puts back 90 / 15 / 1.50. Caps are 0 to 1,000 USD; a cap
  of 0 switches every Claude call off.
- Over the API: `POST /api/ai/budget` with any of
  `{"lifetimeUsd": 90, "monthlyUsd": 15, "dailyUsd": 1.5}`;
  `GET /api/ai/budget` shows caps, spend, what is left, the spend per job and
  day, and the last calls.
- By hand: `<data>/ai/budget.json` holds the same three fields. A missing or
  broken file means the defaults.

New caps apply to the next call, in every process. Lowering the lifetime cap
below what has been spent stops all calls without another alert.

### Prices

`config/ai_prices.json` is the one price table, compiled into the engine: the
published list prices (USD per million tokens, checked 2026-10-06) for input
and output, with cache writes at 1.25 times and cache reads at 0.1 times the
input price (Opus 5.5's own cache read rate where the list gives one), Haiku
5.5's higher rate above 100K prompt tokens, and batches at half price. A model
not in the table is costed at the most expensive row. When prices change, edit
that file and rebuild; the `estimate` flag shows in the app when the figures
are not the published ones.

| Model | Input | Output |
|---|---|---|
| `claude-haiku-5-5` | $0.10 | $0.50 |
| `claude-sonnet-5-5` | $2.00 | $10.00 |
| `claude-opus-5-5` | $4.00 | $20.00 |

### Keeping cost down

- The right model per job: Haiku where the job is a narrow check (the
  critic, the overlay), Sonnet where it reads a lot and writes for the owner
  (the brief, the weekly review, the questions), Opus once a week where depth
  pays (the director).
- Batches: every scheduled job goes through the Message Batches API at half
  price. If the daily brief's batch has not finished after 10 minutes (the
  critic's after 20) it is cancelled (and counted at its worst case) and asked
  once directly. The digest quotes the brief only when today's is ready. The
  director waits up to 55 minutes.
- Prompt caching: the fixed system prompt of every call is marked for the
  cache. It pays where calls repeat within five minutes: the questions (the
  instructions and the fact sheet are one cached prefix, rebuilt at most every
  15 minutes, so a conversation reads it at a tenth of the price), the
  overlay, a retry. The short instructions of the brief and the critic are
  under the models' minimum cacheable length, so there the mark does nothing
  and costs nothing. The language and other per-call words go into the user
  message, never into the cached system prompt.
- Small answers: the critic allows 1,500 output tokens and Haiku answers it
  without thinking first; the brief 8,000 (Sonnet thinks first); the questions
  6,000.

## The key

The key lives on the server in `/etc/pythia/alerts.env` as
`ANTHROPIC_API_KEY` (the owner's setup script writes it there). The autopilot
engine reads that file at start; the AI jobs and the chat service get it
through `env_file` and use it only to compute the hash they show the engine.
The key is never printed, logged, written elsewhere or sent anywhere but to
the Claude API. Without a key nothing is called: the engine answers 503 and
the jobs end quietly.

## Deploying it

- The engine image (`server/Dockerfile`) has the budget compiled in. Both
  engine containers need the ledger folder mounted:
  `-v /srv/pythia-data/ai:/data/ai` (`research/ops/bootstrap.sh` does this for
  new containers; existing ones are recreated with the extra flag). Without the
  mount the ledger lives inside the container and is lost when the container
  is recreated. The new limits (32,000 output tokens, 800,000 characters) and
  the per-job spend need the new engine image.
- `research/ops/deploy_lab.sh` for the lab code, `research/ops/deploy_ops.sh`
  for the jobs (`ai-brief`, `ai-critic`, `ai-weekly`, `ai-director`), then the
  chat container once (`research/ops/README.md`, "Questions in Telegram"). The
  `ai` folder is in the nightly backup.

## Testing

No test calls the API. The engine's tests run every path against a local mock
of the Messages and Batches endpoints (`ai_budget_tests.rs`: refusal at each
cap, the ledger surviving a restart and being shared, the spend per job and
day, alerts, cost math, an unreadable answer, a refusal, a batch that does not
finish, nothing called without a key); the lab's tests use a fake engine and
a fake Telegram (`tests/test_ai.py`: the brief, the fact sheet, the critic and
its checks, the director's drafts, the chat's refusals, limits and logging).
