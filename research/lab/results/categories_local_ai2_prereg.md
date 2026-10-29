# AI2: the pump.fun name categories on the local models. Pre-registration

Registered 2026-10-29 and committed before the first local name was classified and before the one-at-the-buy call
was timed, so before any local category or timing number exists. Brief AI2 of the training plan of 2026-10-28, on
the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3: one trial registry, every number a
trial), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and T15
(`results/analyst_local_prereg.md`, the same chain for the weekly analyst). Code: `lab/pumpfun_rt/categorize.py`,
`lab/pumpfun_rt/livecat.py`, `lab/ai/local.py`; tests `tests/test_pumpfun_live_categories.py` with a fake local
backend. Paper research data only: the live service's own file does not change, its category gate stays off
(`category:none` in the blocklist).

## Why a new classifier

The categories came from Claude Haiku 5.5 through the engine's metered endpoint (`lab.ai.engine`). The API credit
ran out (2026-10-28); the job `pumpfun-rt-categories` is off since 2026-10-24 and the live classifier would log an
error every 30 s once the live service runs. A different model sorting the same names is a different classifier,
so its categories are a new series and are never pooled with the API's.

## What is asked

The same system prompt (`categorize.SYSTEM`), the same day line, trending list and `id|name|ticker` lines
(`categorize.prompt`), the same schema (`categorize.SCHEMA`) and the same checks (`categorize.parse`: an id not asked
for, twice or a code not in `CATS` is dropped). Through `lab.ai.local`: the owner's PC through the relay when its
status route says online, else the VPS model (llama.cpp, Qwen3 4B Instruct Q4_K_M, one slot, 4,096 tokens of
context). The local chain gets the schema as `response_format` (JSON schema) and, written out, at the end of the
system prompt; the answer is one JSON object, a ```json fence around it is accepted, nothing is repaired. A name
without a usable answer (no model answered in time, not JSON, dropped by the checks) stays unknown and is asked
again only where the code asked again before (the live classifier's next run, the next coin of that name).

Changed for the small model, nothing else: CHUNK 25 names a call instead of 800 (an 800-name answer is about 12,000
tokens, past the VPS context), one call at a time (one slot), a call may take 180 s. The daily job asks
yesterday's new names most frequent first within a time budget of 4.5 hours (00:40 to at most 05:10 UTC, before
the briefing at 06:00 UTC asks the same model); names left when the budget is spent stay unknown and are counted
(`left`).

## Series

Every row a local model wrote in `<data>/pumpfun_rt/categories/cats.jsonl` has `model`: `<backend>:<model name>`
(`vps:qwen3-4b-instruct`, `relay:<PYTHIA_LOCAL_LLM_RELAY_MODEL>`). A row without `model` is the API's (Claude Haiku
5.5, `claude-haiku-5-5`). The local classifiers treat only rows with a `model` as known, so a name the API sorted is
asked again; a row reusing a name's category carries the model that sorted the name. A study takes one series
(`CategoryIndex.load(model=...)`); the API's and the local ones are never pooled, and the relay's and the VPS
model's are two series. The books and the live gate keep reading every row (a name's first category), as before.

## The one-at-the-buy call: how often in time

`livecat.ONE_TIMEOUT_S` stays 1.5 s. Measured, not guessed, two ways:

1. **From the call log**, now: every successful VPS call in `<data>/ai/local_llm.jsonl` (2026-10-27 to 2026-10-29,
   other uses, read before this registration): the share that took at most 1.5 s, all calls and those that wrote
   at least 12 tokens (a one-name answer is about 15).
2. **On a day of names**, `python -m lab.pumpfun_rt.livecat --timing` (job `pumpfun-rt-cat-timing`, weekly, the
   lock of the categories job so they never run together): 200 distinct names of the last complete UTC day of
   plain coins in the store, drawn with numpy's default_rng(20261029), each asked alone exactly as the gate asks
   (the day's trending list, the one-name prompt, `max_tokens(1)`, the schema), one after another, each with a
   45 s limit so its time is seen. **The number**: the share answered with a valid code within ONE_TIMEOUT_S, with
   a Wilson 95 % interval, per backend; also median and 90th percentile seconds. A best case: at the buy the
   classifier's chunks queue ahead of it on the one slot. Written to `reports/pumpfun_rt/livecat_timing.json` and
   `<data>/pumpfun_rt/categories/timing.jsonl`.

No pass rule: the number decides nothing by itself. It says whether a category gate on the local model could ever
be switched on without skipping nearly every coin as "category unknown"; switching it on stays the owner's step.

## Trials

R5's registry, family hand, counted only (no Sharpe):

- `hand:ai2:categories_<backend>_<model>` per classifier series, registered with its first classified chunk;
- `hand:ai2:livecat_timing_<backend>_<model>` per backend and model timed, registered with its first measurement.
  The log figure (1.) is part of the VPS model's timing trial.
