# Kraken's new-account fee in S1's paper books and R10's cost model. Pre-registration

Registered 2026-10-29 and committed before the first run that makes a number. On the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, the
lockbox from 2026-07-01) and the readiness ladder (`lab.ops.ladder`). L1 (`results/exec_dryrun_l1.md`) found that
Kraken's AssetPairs carries no fee tiers any more and that a new account pays 0.80 % taker by the published
schedule, twice the 0.40 % S1 and R10 assumed. Paper only: no key, no account, no order; nothing a live bot, a
wallet or the engine reads changes.

## What was seen before this file

L1's first report (2026-10-28: AssetPairs' `fees` lists empty, the schedule below), R10's published table
(`results/smallaccount_r10.md`, S1's rows at 0.40 %) and the S1 books' state (`setup_eur` paid at 0.40 %). No
number of the rerun below.

## The fee table (the one source)

Kraken's published fee schedule, https://www.kraken.com/features/fee-schedule, read 2026-10-28 (L1), kept as text
in the repo (`lab/exec/kraken_fee.py`); nothing is downloaded in a run. The tier is the last whose 30-day USD
volume the account reached.

- Spot pairs (a coin against EUR or USD), maker / taker in %: from 0 USD 0.40 / 0.80 (the new account's tier),
  2,500 0.30 / 0.60, 10,000 0.22 / 0.38, 25,000 0.20 / 0.35, 50,000 0.15 / 0.30, 100,000 0.12 / 0.25,
  250,000 0.10 / 0.22, 500,000 0.08 / 0.20, 1,000,000 0.06 / 0.18, 2,500,000 0.04 / 0.15,
  5,000,000 0.02 / 0.12, 10,000,000 0.00 / 0.10.
- Stablecoin and FX pairs (USDC/EUR, EUR/USD): 0.20 % maker and taker at the first tier, the only one kept (L1's
  `FX_FEE`); a small account never leaves it.

A pair's own AssetPairs tiers win when Kraken fills them again (L1's rule, the dry run only; the studies and books
have no live answer).

## Who reads it

One function, `lab.exec.kraken_fee.kraken_fee(vol_usd, maker=False, stable=False)`, a share of the order:

- **The dry run** (`lab.exec.dryrun.fee_rate`): the fallback when AssetPairs' lists are empty, and the FX leg of a
  USD pair (stable).
- **S1's paper books** (`small50_tsmom1`, `small100_breakout_sol3`, and `small50_tsmom1_wk`, which runs S1's rule
  on the same wallet): their only Kraken cost is the way there, EUR to USDC, a stablecoin pair: `kraken_fee(0,
  stable=True)`. A book started at 0.40 % is restated once: the difference times the wallet comes out of its cash
  and into its costs, the date and both fees in its state. `reports/smallaccount/latest.md` names the fee and the
  source. S2's books go there by a SOL swap and do not change.
- **R10's cost model** (`lab.experiments.smallaccount_r10.kraken_costs`): an asset before it could be swapped on
  chain pays the spot taker plus its EUR pair's half spread; the way in and back (EUR to USDC and back) the
  stablecoin fee plus USDC/EUR's half spread. Volume 0: a 40 or 100 EUR wallet would need about 25 to 60 full
  round trips in 30 days to reach 2,500 USD.
- **The ladder**: step 2's "costs of their era" line of an S1 book names the fee from the same function; when the
  rerun's report exists its S1 rows replace R10's for S1.

S1's study itself (`lab.experiments.smallaccount`, its Kraken venue and its published numbers), S2, L1's on-chain
code and F2's factory keep their constants: they are records or feed real-money paths, and are not rerun here.

## The one rerun

R10's two S1 rows (`tsmom1`, `breakout_sol3`) with R10's code and inputs, the corrected fees above as the only
change, at 40 and 100 EUR, filled at the signal close and one close late, over R6's validation window only
(2024-01-01 to 2026-06-30; the lockbox stays shut, no in-sample number). Per row and size: CAGR, max drawdown,
Sharpe and end in EUR, the BTC/ETH benchmark, the DSR of the late daily excess over R5's pool of all and of the
small family (higher is better), and R10's pre-registered verdict (late, at both sizes: CAGR above 0, Sharpe above
the BTC/ETH wallet's, DSR 0.95 or more). Beside it, R10's published rows at 0.40 %, as published.

`python -m lab.experiments.smallaccount_r10 --kraken-fee` (under the heavy lock) writes
`results/kraken_fee_s1.md` below its marker and `reports/kraken_fee_s1/latest.json`.

## Trials

8 counted trials in R5's registry, family small (2 rules x 2 sizes x 2 fills,
`small:kraken_fee_s1:<rule>@<EUR>:<fill>`), registered before the first number by the rerun and again (same ids,
written once) by the books' daily run, so the server's registry has them whoever ran first.

## What would change a decision

None of the S1 rows passed R10's bar at 0.40 %. The Kraken leg before cbBTC (BTC until 2024-11-07) costs twice as
much, the way in and back half as much; a row that passed now would go to step 2 of the ladder, not to money. The books' restated costs and the dry run's fee
make the small path's costs honest before step 5 of the ladder.
