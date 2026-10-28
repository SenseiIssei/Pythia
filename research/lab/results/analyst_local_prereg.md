# T15: the weekly analyst on the local models (e1b). Pre-registration

Registered 2026-10-28 and committed before the first local week was asked, so before any local ranking or score
exists. Brief T15 of the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`,
sections 2 and 3: one trial registry, every number a trial), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`) and X11 e1 (`results/model_upgrades_prereg.md`, section e). Code:
`lab/ai/analyst.py`; tests `tests/test_model_upgrades.py` with a fake backend. Shadow only: no paper book, live bot,
wallet or engine reads anything here.

## Why a new experiment

e1 asked Claude Sonnet through the engine's metered endpoint. The API credit ran out (2026-10-28 05:33 UTC, HTTP
400 "credit balance is too low"); the job `ai-analyst` was red. e1 recorded one week (2026-10-21, reference day
2026-10-20, 31 coins) and stops there. A different model answering the same question is a different forecaster,
so its weeks are a new series and are never pooled with e1's.

## What is asked

The same question as e1, through `lab.ai.local` (the chain the briefing and the news tags use, no API credit, no
key): first the owner's large model on his PC through the relay when its status route says it is online, else the
VPS model (llama.cpp, Qwen3 4B Instruct Q4_K_M, `research/ops/local-llm.sh`). Temperature 0.2, at most
120 + 40 tokens a coin out.

The prompt is e1's fact sheet with two changes, both for the VPS model's context of 4,096 tokens (prompt and
answer together; e1's prompt alone was about 3,150 tokens on 32 coins, counting a digit as a token as Qwen's
tokenizer does, and the answer needs about 1,400):

- the facts per coin are one table row instead of one sentence, and the coin's close and reference day are left
  out (the day is named once, and per row only when a coin's differs; the close says nothing about a 7-day rank).
  Every other fact stays: 7, 30 and 90-day returns, 30-day vol, distance to the 52-week high and the 200-day mean,
  28-day volume trend, 7-day funding, the market lines. About 1,700 input tokens on 32 coins.
- the reason per coin is at most 8 words (e1: one sentence of at most 20), and the answer's JSON shape is written
  out in the system prompt (the local chain has no schema parameter). The reason is not scored.

## The answer, checked strictly

One JSON object (a ```json fence around it is accepted) whose `ranking` holds every asked coin exactly once, with
an integer `expectedRank` from 1 to n, each rank once, and `pUp7d` from 0 to 1. Nothing is repaired: no
renumbering, no dropping, no default. A bad answer (not valid JSON, a coin missing, unknown or twice, a rank
repeated or out of range, a probability out of range) is asked again once on the same backend, the problem named
in the prompt. A second bad answer, or no answer from any backend, skips the week: one line in
`<data>/ai/analyst_skips.jsonl` (day, backend, model, why), no ranking recorded, the job exits 1. A skipped week is
never filled in later; the next call waits for the next rebalance of the M2 v2 book, as every week does.

## Series

Every record in `<data>/ai/analyst.jsonl` names its `backend` (`relay` for the owner's PC, `vps`) and `model` (the
backend's model name, `PYTHIA_LOCAL_LLM_RELAY_MODEL` or `PYTHIA_LOCAL_LLM_MODEL`, default `qwen3-4b-instruct` on
the VPS). A series is one backend and one model; a new model name on either backend starts a new series. e1's
Claude records (no backend field) are the series `claude` and stay as they are. A week belongs to the series that
answered it; a series has no week where another model answered (no mixing, no filling).

## Scoring and pass rule (e1's, per series)

Unchanged from e1: per week the rank IC (Spearman) of minus `expectedRank` against the realised 7-day log return
from the reference close, next to the low-vol rank (minus 30-day vol), 28-day momentum and, where the M2 shadow
recorded the same reference day, M2's rank; Brier of `pUp7d` against the coin's base rate of up weeks. **Pass**,
after at least 26 scored weeks of that series: mean weekly IC above 0 with t above 2, and above the low-vol rank's
on the same coin-weeks with a paired t above 2. Until then, and unless it passes, a series is a shadow record;
passing only opens a registered ensemble study, nothing trades on it. The report
`<data>/reports/ai_analyst/latest.json` holds every series' score (`series`) and shows the series of the newest
week on top; the briefing's lab card names the model and backend that answered.

## Trials

One trial per series in R5's registry, family hand, counted only (no Sharpe): `hand:t15:analyst_e1b_<backend>_<model>`
(for example `hand:t15:analyst_e1b_vps_qwen3-4b-instruct`), registered when the series' first week is recorded,
before any of its weeks is scored. The PC model and the VPS model are one trial each; a later model is another.

## Addendum 2026-10-28, before the relay's first week

The first local week (2026-10-28, reference day 2026-10-27) went to the VPS model, because the relay was not
configured on the server yet; it answered GRT twice, then on the retry a coin not asked for, so that week is skipped
and stays skipped. From the next rebalance on the relay is configured. The PC's model (`sensei-qwen38`) is asked
with thinking off (`reasoning_effort` "none", `lab.ai.local`): with thinking on it wrote four times the tokens for
the same answer. That is part of the series: asking it with thinking on is a different forecaster and needs another
model name (an alias in Ollama), so it becomes a series and a trial of its own. Nothing else changes.
