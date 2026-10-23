# Memecoins through Jupiter for our own wallet: three rules and their proof (pre-registration, 2026-10-23)

Written and committed together with the code and before any paper book of this module has run, quoted or
traded. Code: `lab/onchain/meme_safety.py` (the safety check), `lab/onchain/meme.py` (candidates, rules,
paper books, this proof), `lab/onchain/meme_live.py` (the locked live path); tests
`tests/test_onchain_meme.py`; description `docs/ONCHAIN-MEME.md`. A change to any number below after the
first journal row is a new trial with a new name and a new date in this file, in git; nothing here may be
loosened after a result is known.

## Why

Y5 to Y9 (`results/pumpfun_*.md`) found no pump.fun rule that wins reliably: no filter beat P_pool0, and most
coins go to zero. This module asks a different question on different venues: do coins that pass a strict
per-coin safety check, bought through Jupiter on Raydium (LaunchLab included), Meteora (its dynamic bonding
curve included), Orca or PumpSwap and held minutes to a day, make money after every cost? Paper first; real
money only through the proof below and the owner's written ack.

## Trials: 3

| rule | entry (all also: safety check passed, no `rug_risk` badge in the Trends file, not bought in the last 24 h, at most 5 open) | exits |
|---|---|---|
| `fresh_win` | a coin of the Trends file's fresh list (migrated in the last 30 min), 5 to 30 min after its migration, with the Y9 model's `win_high` badge | +50 % take profit, -25 % stop, trailing 20 % below the peak once the peak is +20 %, time stop 2 h, liquidity drop 50 % |
| `momentum_trail` | its oldest pool at least 24 h old, its best pool at least 50,000 USD, the best pool's price up at least 5 % over 1 h and 20 % over 24 h (DexScreener) | -15 % stop, trailing 15 % below the peak, time stop 24 h, liquidity drop 40 %, no take profit |
| `organic_trend` | on Jupiter's `toporganicscore/1h` list with organic score at least 80, Jupiter's price change over 1 h and over 24 h above 0, its oldest pool at least 24 h old | +30 % take profit, -10 % stop, trailing 10 % below the peak once +5 %, time stop 12 h, liquidity drop 40 % |

Returns are on the position's cost (0.1 SOL plus the buy's fees) against the SOL a real Jupiter sell quote of
every unit brings, less the sale's fees, checked every run (every 2 minutes). Liquidity drop: the best pool's
USD liquidity under the share of its value at entry. A position without a sell quote for 30 minutes is closed
at zero.

These 3 trials join the global pool: 907 hand trials, 600 factory genomes and 386 pump.fun trials
(`pumpfun_rt.study.pool` on 2026-10-23: 1,893, bar 2.45) plus these 3: **1,896**. The proof computes the
pool afresh each day (`meme.global_pool`) and adds the 3.

## Candidates

The Trends file (`reports/pumpfun_rt/trends.json`, used only when written in the last 2 minutes: fresh list
and migrated coins of the hot list, with badges), DexScreener's `token-boosts/top/v1` and
`token-profiles/latest/v1` on Solana, and Jupiter's `tokens/v2/toptrending/1h` and `toporganicscore/1h`.
Each candidate's pools from DexScreener's `tokens/v1/solana`. At most 10 new safety checks a run.

## The safety check (a coin no rule may quote without)

All must hold (`meme_safety.judge`): the mint exists under the classic Token program (Token-2022 refused,
whatever its extensions), initialised, no mint authority, no freeze authority (both lifted only for a mint on
the owner's exception list); a pool on Raydium, LaunchLab, LetsBonk, Meteora, Orca or PumpSwap (never pump.fun's
own curve) with at least **20,000 USD** in its best pool; the 10 largest holders, pools, program vaults (owners
off the ed25519 curve) and burn addresses left out, under **30 %** of the supply outside the burn addresses
(Jupiter's audit share only when the chain cannot be read; neither: refused); the first pool at least
**5 minutes** old; neither the mint nor a creator (Jupiter's `dev`, the metadata's update authority and
creators) on the owner's block list. Paper accepts a verdict up to 10 minutes old; a real buy needs one from the
last minute.

## Paper

Per rule one book, `paper/onchain_meme_<rule>/`: 1 SOL, 0.1 SOL a buy, filled at Jupiter's quoted out amount
less Solana's base fee (5,000 lamports) and our priority fee (0.0001 SOL), stage 1's executor; the token
account rent is not a cost. Journal equity on the 10,000 basis.

## The proof (`python -m lab.onchain.meme --proof`, daily: `reports/onchain_meme/proof.json`)

Each rule alone, over its whole record from its first journal row; all six must hold:

| # | check | passes when |
|---|---|---|
| P1 | days | at least **30** journal days |
| P2 | trades | at least **100** closed trades |
| P3 | mean | mean net return per trade above 0 and the lower end of its 90 % bootstrap band (whole hours resampled, `pumpfun_rt.study.boot_mean`) above 0 |
| P4 | breadth | P&L above 0, the 5 best trades under **half** of it, at least **50 %** of days positive |
| P5 | deflated | deflated Sharpe probability of the daily returns above **0.95** against the global pool (above) |
| P6 | quotes | at most **5 %** of planned entries and exits without a usable quote |

Only a passed proof (at most 36 hours old) lets the live gate consider a rule, and only when the owner names it
in the ack's `[meme]` section (code maxima: 50 USD of meme coins, 10 USD a swap, 10 USD of meme losses a day).
Passing never arms anything.

## What does not count

Days before a book's first journal row, replayed days, trades made while the Trends file was stale (none are:
the rule does not enter then), and anything the pump.fun bot does: its gates (`docs/PUMPFUN-LIVE.md`) are
untouched by this registration.
