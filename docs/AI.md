# The Claude API in Pythia

Pythia's own models come first. The Claude API is a data provider that is
called rarely, for two scheduled jobs, behind a hard budget. Everything it
says is recorded and scored in shadow mode; nothing it says sizes, places or
vetoes an order.

## What is called, and when

| What | When | Model | Size of one call | Expected cost |
|---|---|---|---|---|
| Daily brief (`lab.ai.brief`, jobs.yaml `ai-brief`) | every day 06:50 UTC | `claude-haiku-5-5`, Batches API | about 6,000 tokens in, under 1,000 out (at most 1,500) | about $0.0005 a day |
| Weekly review (`lab.ai.weekly`, jobs.yaml `ai-weekly`) | Sundays 09:00 UTC | `claude-sonnet-5-5`, Batches API, effort medium | about 15,000 to 20,000 tokens in, up to 8,000 out | about $0.03 to $0.05 a week |
| AI overlay (Signals page) | only while switched on, one market every `PYTHIA_AI_INTERVAL_SEC` (120 s) | `claude-haiku-5-5` unless set otherwise | about 900 tokens in, under 100 out | about $0.09 a day while on |
| One signal, an ensemble forecast, a key test | when asked for in the app | the provider's default (Haiku for Claude) | under 2,000 tokens | well under a cent |

Expected total with the overlay off: about **$0.20 a month**, roughly $2 a
year. `claude-opus-5-5` is never a default anywhere; it runs only where a model
is named explicitly.

**Daily brief.** One request covers every coin. It reads what Pythia already
has: daily closes (1, 7 and 30-day returns, 30-day volatility, distance to the
200-day mean and the one-year high), settled perp funding, the running
autopilots, and the headlines of the lab's feeds (forward report, learning
loop, listings, trending, factory, models). Our own models' forecasts are not
shown to it, so its calls stay independent of what they are scored against.
It answers in a JSON schema: for BTC, ETH and every coin a running autopilot
trades, the probability that the close 7 days after the latest close is
higher, with one line of reason, plus three plain lines that the daily
Telegram digest quotes under "AI brief (shadow)". The answer is checked before
anything is kept (a coin not asked for, a duplicate, a probability outside 0
to 1 is dropped and named). It goes to `reports/ai_brief/latest.json`, which
also shows up on the Research page.

**Weekly review.** Reads an excerpt of every study write-up, the headlines of
every lab report, the forward evidence, the autopilots, the brief's own score
and last week's proposals, and proposes the three most promising next
experiments with a falsifiable hypothesis, a test design with costs, a pass
criterion fixed in advance, the effort, and what could fool us. Written to
`reports/ai/weekly.md` (and a dated copy). Proposals only: nothing reads the
file to run anything.

Both jobs run once per day or ISO week; running one again the same day or week
does nothing unless `--force` is given. `--dry-run` prints the prompt and its
size and calls nothing.

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
reliability, per coin and per week. Below 30 resolved calls the verdict is
"too early". The Models page shows it as **LLM vs our models**, with the latest
brief and the weekly review. Run `python -m lab.ai.score` to rescore without a
call.

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

| Cap | Default | Period |
|---|---|---|
| Lifetime | $90.00 | every call ever |
| Monthly | $15.00 | the calendar month, UTC |
| Daily | $1.50 | the day, UTC |

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
  `GET /api/ai/budget` shows caps, spend, what is left and the last calls.
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

- Batches: both scheduled jobs go through the Message Batches API at half
  price. If the daily brief's batch has not finished after 20 minutes it is
  cancelled (and counted at its worst case) and asked once directly.
- Small answers: the brief allows 1,500 output tokens and Haiku answers it
  without thinking first; the overlay's signal allows 1,024.
- Prompt caching: the fixed system prompt of every call is marked for the
  cache. It pays off where calls repeat within five minutes (the overlay, a
  retry); a once-a-day call gains nothing from it and loses next to nothing.

## The key

The key lives on the server in `/etc/pythia/alerts.env` as
`ANTHROPIC_API_KEY` (the owner's setup script writes it there). The autopilot
engine reads that file at start; the two AI jobs get it through `env_file` and
use it only to compute the hash they show the engine. The key is never
printed, logged, written elsewhere or sent anywhere but to the Claude API.
Without a key nothing is called: the engine answers 503 and the jobs end
quietly.

## Deploying it

- The engine image (`server/Dockerfile`) has the budget compiled in. Both
  engine containers need the ledger folder mounted:
  `-v /srv/pythia-data/ai:/data/ai` (`research/ops/bootstrap.sh` does this for
  new containers; existing ones are recreated with the extra flag). Without the
  mount the ledger lives inside the container and is lost when the container
  is recreated.
- `research/ops/deploy_lab.sh` for the lab code, `research/ops/deploy_ops.sh`
  for the two jobs. The `ai` folder is in the nightly backup.

## Testing

No test calls the API. The engine's tests run every path against a local mock
of the Messages and Batches endpoints (`ai_budget_tests.rs`: refusal at each
cap, the ledger surviving a restart and being shared, alerts, cost math, an
unreadable answer, a refusal, a batch that does not finish, nothing called
without a key); the lab's tests use a fake engine (`tests/test_ai.py`).
