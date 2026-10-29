# AI2: the Telegram chat and the name categories on the local models

2026-10-29. Pre-registration: `results/categories_local_ai2_prereg.md` (its own commit, before any number here).
Brief AI2 of the training plan of 2026-10-28. The metered API has no credit since 2026-10-28; its three remaining
users now ask `lab.ai.local` (the owner's PC through the relay when it is online, else the VPS model, Qwen3 4B
Instruct on llama.cpp). Paper only: the live service's own file is unchanged, its category gate stays off
(`category:none`).

## What changed

- **The Telegram chat** (`lab/ai/chat.py`, container `pythia-ai-chat`) answers through the local chain, with the same
  plain refusal check before any call, the same instructions and the same scrub of anything that looks like a
  secret. Every answer ends with the model and where it runs (`qwen3-4b-instruct (VPS)`, the PC's model `(PC)`).
  The daily cap (`PYTHIA_AI_ASK_PER_DAY`, 40) is unchanged. The fact sheet (about 11,000 tokens) is cut to what
  fits each backend's context: the date first, then the sections that share the most words with the question. A
  question those facts do not answer (the model's kind `no_facts`) gets a fixed line saying so. So does an answer
  with a number that is in neither the facts it got nor the question (`lab.ai.local.foreign_numbers`). The
  withheld text and the reason go to `chat.jsonl`.
- **The name categories** (`categorize.py`, the daily job; `livecat.py`, the live classifier and the one-at-the-buy
  call) keep `SYSTEM`, `SCHEMA` and `parse` unchanged. The local chain gets the schema as `response_format` and
  written out under the system prompt. A name without a usable answer (no model in time, not one JSON object,
  dropped by `parse`) stays unknown.
- **A different model is a different classifier.** Every row a local model writes in `cats.jsonl` has
  `model` = `<backend>:<model>` (`vps:qwen3-4b-instruct`, `relay:<the PC's model>`). A row without the field is
  the API's (Claude Haiku 5.5, `claude-haiku-5-5`). The local classifiers count only local rows as known, so a name
  the API sorted is asked again. **No study may pool the API's categories with the local ones, nor the relay's
  with the VPS model's.** To get one series, use `CategoryIndex.load(model=...)`. The books and the live gate still
  read every row (a name's first category), as before.
- **The job `pumpfun-rt-categories` is on again**, at 00:40 UTC with a budget of 4.5 hours (timeout 5 h). It asks
  25 names a call, one call at a time (the VPS model has one slot), the most frequent names first. Names left when
  the budget runs out stay unknown (`left` in `runs.json` and the report). It turns red only when no model answered
  at all. Before AI2 the API sorted about 7,300 new names a day. At about 15 answer tokens a name and 0.08 to
  0.12 s a token on the VPS model (the log below, prompt time included), that is roughly 2.5 to 3.5 hours. This
  is an estimate, not a result: `left` in `runs.json` shows what each night really missed. `--force` on a day
  asks what was left.

## The one-at-the-buy call: how often in time (ONE_TIMEOUT_S 1.5 s)

1. **From the call log** (`<data>/ai/local_llm.jsonl`, 2026-10-27 22:10 to 2026-10-29 08:10 UTC, every successful
   VPS call of the briefing, the news tags and the analyst): **1 of 86 calls took at most 1.5 s (1.2 %, 95 % 0.2
   to 6.3 %), and 0 of the 85 that wrote 12 tokens or more (0 %, 95 % 0 to 4.3 %)**. The fastest of those took
   1.71 s. A one-name answer is about 15 tokens after a prompt of about 720 (the system prompt 508, the day,
   trending list and name 216, in `analyst.est_tokens`).
2. **On a day of names** (200 names, seed 20261029, each asked alone as the gate asks, the share in time per model):
   `python -m lab.pumpfun_rt.livecat --timing`, job `pumpfun-rt-cat-timing` (Sundays 11:30 UTC, first on
   2026-11-01; or by hand). It could not run in the build container, which cannot reach the VPS model. Its number
   goes to `reports/pumpfun_rt/livecat_timing.json` and is added here.

What it means: on the VPS model the call at the buy practically never answers in time. A category gate on it would
skip almost every coin whose name was not classified before as "category unknown". The live classifier's answers
every 30 s, the daily job's cache and reused names are what a gate could use. Switching a gate on stays the
owner's step (it is off).

## Trials (R5's registry, family hand, counted only)

`hand:ai2:categories_<backend>_<model>` per classifier series, with its first classified chunk;
`hand:ai2:livecat_timing_<backend>_<model>` per backend and model timed. The log figure above belongs to
`hand:ai2:livecat_timing_vps_qwen3-4b-instruct`, registered with the first `--timing` run (the build container
reads the registry only).

## Tests

`tests/test_pumpfun_live_categories.py` (a fake of the local chain and a slow OpenAI-compatible server: a category
row carries its model, the API's rows are another classifier, a timeout at the buy is unknown, an unreadable
answer is unknown, the time budget, the job's exit code, the timing), `tests/test_pumpfun_pipeline.py`,
`tests/test_ai.py` (the chat names its model, the facts that fit the VPS context, no_facts and the number rule, no
model), `tests/test_ai_local.py` (the schema as `response_format`, the model in the answer), `tests/test_jobs.py`.
