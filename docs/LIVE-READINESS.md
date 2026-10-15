# Real money readiness: the pre-registered rule

**Set on 2026-10-15.** The owner decided that Pythia trades real money on
Alpaca only once an autopilot makes profit actively and consistently on the
Alpaca paper account. This page is that decision as numbers, written down
before the results it will judge. A change to a number is a change to this
page and to the constants in `research/lab/lab/ops/readiness.py` in the same
commit, with a new date, so every change shows in git.

Meeting the rule does one thing: the owner gets one Telegram post saying the
autopilot is ready for a real money proposal, with its numbers. Nothing is
armed, changed or traded. Only the owner can arm live (SAFETY.md).

## Who is judged

Every running or paused autopilot that is not already live, and every sleeve
of an autopilot with several sleeves (a sleeve has its own P&L and trade
count). Only the paper record counts: mode demo, orders on the Alpaca paper
account. Every number is after fees.

A restarted autopilot (stopped, then started again under the same id) is a new
run: its days, weeks and drawdown start again from the new start. A sleeve's
record starts when the check first saw it in the run, or at the run's start
when it was there in the check's first look within a day of the start.

## The rules

All nine must pass.

| # | rule | passes when |
|---|------|-------------|
| 1 | record | on the Alpaca paper account for at least the risk step's minimum days, with at least **20 closed trades**. Without a backtest band (rule 6), **15 more days** |
| 2 | profit | net P&L above zero over the whole period |
| 3 | weeks | positive in at least the risk step's number of the last **4 complete calendar weeks** (Monday 00:00 UTC to Monday). A week that ended before the start counts as not positive |
| 4 | benchmark | ahead of its benchmark over the period: BTC, SPY or the blend, as the engine reports it. No benchmark return (a start price still missing): fails |
| 5 | drawdown | the deepest fall from a peak at most the risk step's limit, and not deeper than the backtest band's 95th percentile dip where the band has one |
| 6 | band | the forward report (`reports/forward/`, at most 36 hours old) has it inside its backtest band, or above it. Below fails. No band: passes, and rule 1 asks for 15 more days |
| 7 | reconcile | the engine's reconciliation of the Alpaca paper account clean on each of the last **7 days** (this check records it once a day; a reconciliation older than 6 hours does not count), and no unexplained finding (mismatch, untracked pair, stray order) in the engine's log over those days |
| 8 | inflation | the annualised net return above inflation: the higher of US CPI year over year (FRED CPIAUCSL) and euro area HICP year over year (Eurostat). Fetched once a day, the last cached figure when a source is down; the report says which figure was used |
| 9 | ETF | the annualised net return above the risk step's ETF hurdle. The S&P 500 over the same days (FRED SP500, price only) is shown next to it for information; no rule reads it |

Annualised means compounded to a year: `(1 + return) ^ (365 / days) - 1`.
Over 30 to 45 days that number is noisy: a lucky month looks like a great
year. Rules 2, 3 and 5 are there so one good stretch is not enough.

Rule 6 lets "above the band" pass: better than the backtest expected is not a
reason to refuse, and rules 2, 3 and 5 still have to hold.

Rule 7 is account wide: the reconciliation compares the whole Alpaca paper
account with Pythia's books, so an unexplained difference holds back every
autopilot on it.

## The risk slider

The readiness card on the Autopilot page has one slider, careful to bold. One
step sets four numbers together; the middle step is the default. The engine
saves the choice to `reports/readiness/settings.json` (`risk_step`), the
daily check reads it, and every report and alert says which step it used.

| step | name | max drawdown | ETF hurdle a year | positive weeks of 4 | minimum days |
|------|------|--------------|-------------------|---------------------|--------------|
| 1 | careful | 5 % | 7 % | 4 | 45 |
| 2 | cautious | 7.5 % | 8.5 % | 4 | 41 |
| 3 | balanced (default) | 10 % | 10 % | 3 | 38 |
| 4 | brave | 17.5 % | 11.5 % | 3 | 34 |
| 5 | bold | 25 % | 13 % | 2 | 30 |

Bold accepts a deeper drawdown and fewer good weeks after fewer days, so it
must also earn more: the ETF hurdle rises with the step. Careful accepts a
lower return because a strategy that never falls more than 5 % is worth more
than an index fund that can fall 30 %.

The first version of this rule (written the same day, before the slider) was
30 days, 3 of 4 weeks and a 10 % drawdown; the slider's middle step keeps the
weeks and the drawdown and asks for 38 days.

## Where it runs

- `python -m lab.ops.readiness` (research/lab), the job `readiness` in
  `research/ops/jobs.yaml`: right after the learning loop (`depends_on:
  [learn]`), before the daily digest.
- It reads the engine's `GET /api/state`, the forward report, the two
  inflation sources and the S&P 500 index. It writes
  `reports/readiness/latest.json` (the lab feed header plus every rule per
  autopilot), `<data>/readiness/history.jsonl` (one line a day: equity, P&L,
  trades and benchmark per autopilot and sleeve, and the reconciliation) and
  `<data>/readiness/state.json` (what was announced).
- The daily digest has one line on it; the Autopilot page shows a compact
  card per autopilot with the rules that pass and the days to go.
- When an autopilot or sleeve newly meets every rule, one Telegram post
  (category Autopilot events), at most once a week for the same run.

## Changes

| date | change |
|------|--------|
| 2026-10-15 | First version: rules 1 to 9, the risk slider and its five steps. |
