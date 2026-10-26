# L1: the relaxed long-term book for the on-chain wallet (0.5 SOL, about 45 EUR)

Task L1, 2026-10-26. Code `lab.onchain.longterm` (signal, backtest, cost per swap), the book's entry in
`lab.onchain.book.BOOKS`, the cheapest send path in `lab.onchain.live_exec` / `fees` / `live_gate`, job
`onchain-longterm`. Paper from the deploy; nothing live is switched on. The owner arms it (below).

## Which rule, and why

S2 (`results/smallaccount_s2.md`) found that nothing beats holding the S&P 500 token convincingly, and exactly one
candidate passed its bar (drawdown under 20 %, CAGR at most 1 point below the ETF token): **tsmom1**, S1's
`tsmom_top20` on the single most liquid coin. The task says to take S2's winner when there is one, so the book is
tsmom1: the day's most liquid coin (BTC, some days ETH) held while its 28-day return is above 0 and BTC is above its
200-day average, sized to 40 % annual vol, the rest USDC, decided daily after the close (S1 and S2 both ran it daily).
Out of sample at 40 EUR in S2: 28.5 % a year, drawdown 17.8 %, against SPYx held 20.4 % and 18.1 %. It passed, but
not convincingly (band of its lead -22.6 to +48.2 points, deflated p 0.65): about as safe as the ETF by drawdown,
with a chance to grow more, and no proof that it will.

- **Coins and mints:** BTC as cbBTC, ETH as WETH, USDC as the safe asset, SOL only for fees; all four are in
  `lab.onchain.mints` and on the guard's route list. A day whose most liquid coin is anything else is USDC.
- **No ETF or gold token.** S2 recorded working Jupiter routes for SPYx and PAXG, but both are Token-2022 and the
  stage-2 guard refuses every Token-2022 account (`guard.check_accounts`); widening the guard is out of scope.
  tsmom1 needs neither.
- **ETH at most 25 % of the book** (`live_gate.MAX_ETH_SHARE`, WETH is bridged): written into the signal, so the
  paper twin holds what the live trader can hold. On S2's 65 ETH days out of sample the rest of the weight is USDC.
- **Cadence daily**, one look per new signal; the band below keeps the swaps few.

## The band and the swaps

No swap for a change under 10 % of the book or under 3 USD, whichever is larger (`book.min_trade`, 5 USD at 50 USD);
a coin leaving the book is sold whole. No swap above a quarter of the wallet's value (the live cap with
`limits=wallet`); a larger order goes as several swaps. The same entry in `BOOKS` drives the paper twin and
`live_exec.book_swaps`. The live book also never counts more USDC than the wallet holds (`wallet_cash`): with the
owner's share from the app, the existing `book_state` counts the share of the wallet's value less what the book
bought, which overstates the cash once the coins have risen; this book is sized on the real USDC, like its twin.
The other books are unchanged.

The book's own rules over S1's windows (`python -m lab.onchain.longterm --backtest`, 50 USD, 0.035 SOL reserve
marked at SOL's close, S1's recorded half round trips, every piece its own network fee):

| window | run | CAGR | max DD | Sharpe | swaps a year | costs a year | costs / gain |
|---|---|---|---|---|---|---|---|
| 2020-08 to 2023 | onchain_longterm | 65.2 % | 18.1 % | 2.04 | 48 | 0.13 USD | 0.2 % |
| 2020-08 to 2023 | with the other books' fee | 65.0 % | 18.3 % | 2.04 | 48 | 0.28 USD | 0.4 % |
| 2020-08 to 2023 | without the band (5 USDC) | 64.8 % | 18.3 % | 2.04 | 59 | 0.13 USD | 0.2 % |
| 2020-08 to 2023 | BTC held | 45.2 % | 76.6 % | 0.90 | | | |
| 2024 to 2026-10-21 | onchain_longterm | 28.5 % | 19.3 % | 1.08 | 77 | 0.31 USD | 1.7 % |
| 2024 to 2026-10-21 | with the other books' fee | 26.5 % | 20.1 % | 1.02 | 76 | 1.31 USD | 7.3 % |
| 2024 to 2026-10-21 | without the band (5 USDC) | 28.2 % | 19.0 % | 1.08 | 78 | 0.32 USD | 1.7 % |
| 2024 to 2026-10-21 | BTC held | 25.8 % | 53.0 % | 0.72 | | | |

The band changes little (the rule's weight moves slowly); the fee path matters more: with the Sender tip and the
0.0001 SOL priority the same swaps cost four times as much, 2 points a year at this size. A full entry is about four
swaps (a quarter of the wallet each), so the swap count is higher than S2's order count.

## The cheapest execution

For this book only (`live_exec.Trader.cheap`, a book with `cheap` in `BOOKS`): never through Helius Sender and
without a tip, so `PYTHIA_ONCHAIN_SENDER` can stay unset (the plain RPC alone; even when Sender is set for other
swaps, this book's never go through it). The priority fee is `fees.cheap_price`: the 25th percentile of the recent
prioritization fees of the accounts the swap writes, at least 1,000 micro-lamports a unit (about 250 lamports for a
swap of 250,000 units); if the blockhash passes without landing, the next attempt bids the 50th, then the 75th
percentile, each at least 1.5 times the last; never above 0.00002 SOL a swap (`fees.CHEAP_MAX_PRIORITY_L`), far
under the guard's 0.0005. Three attempts of 60 to 150 s each: it lands within a few minutes or is retried with the
next signal. The slippage is fitted to the size (`live_gate.fitted_slippage`: 15 bps up to 25 USD, 20 up to 100,
else the coin's 30), never looser than before. Jupiter routes only, keyless (no paid plan). The SOL reserve: the
trader keeps its 0.02 SOL plus the room for one swap (about 0.0226 SOL, unchanged) and refuses any swap below it;
the paper wallet keeps 0.035 SOL: that, the rent of the USDC, cbBTC and WETH accounts (0.0061 SOL, paid by the
first swaps) and a year of fees. The task's "about 0.01 SOL" would mean lowering the trader's reserve, which this
task does not do; the reserve is 7 % of this wallet and earns nothing.

Cost per swap on the recorded quotes (`results/smallaccount_s2_quotes.csv`, 2026-10-24; SOL at 100.7 USD), bps of
the swap: the route's half round trip (below 0 read as 0) plus the network fee; the cheapest path at its floor
(0.0000053 SOL) and at its cap (0.000025 SOL with the base fee, 0.25 cent), the other books' path 0.00011 SOL
(1.1 cent):

| coin | swap | route, half round trip | cheapest path | cheapest at its fee cap | the other books' path |
|---|---|---|---|---|---|
| BTC | 5 USD | -1.7 | 1.1 | 5.0 | 22.1 |
| BTC | 10 USD | 0.9 | 1.5 | 3.5 | 12.0 |
| BTC | 25 USD | 0.1 | 0.3 | 1.1 | 4.6 |
| BTC | 50 USD | 2.6 | 2.7 | 3.1 | 4.8 |
| ETH | 5 USD | -2.0 | 1.1 | 5.0 | 22.1 |
| ETH | 10 USD | -3.1 | 0.5 | 2.5 | 11.1 |
| ETH | 25 USD | 1.3 | 1.6 | 2.4 | 5.8 |
| ETH | 50 USD | -0.7 | 0.1 | 0.5 | 2.2 |
| ETH | 100 USD | 6.7 | 6.8 | 7.0 | 7.8 |

At the book's usual 10 to 13 USD swaps: about 1.5 to 3.5 bps, under a cent a swap. Every real swap is measured
again (`live/onchain/execution.jsonl`, `reports/onchain/execution.md`: fee paid, priority, send to land).

## Paper first (from the deploy)

Job `onchain-longterm` after `paper-families`: writes `signals/onchain_longterm/latest.json` (36 h valid,
experimental, never run by the exchange engine), then steps the paper twin `paper/onchain_longterm` through Jupiter
quotes with the live trader's rules: a 0.5 SOL wallet whose first run swaps all but 0.035 SOL into USDC (four swaps,
as the owner's converts would be), then the band, the split, the ETH cap and 0.000025 SOL a swap. Journal on the
10,000 basis (forward report), report `reports/onchain_longterm/`, the hourly mark in `onchain-mark`, and a line in
the morning briefing's paper card ("On-Chain-Langfristbuch (Papier, 0,5 SOL)": value, result, what it holds).
`onchain-execution` and `onchain-live-simulate` are back on (read only, nothing signed or sent).

## What the owner saves to arm it (nothing here does it)

`/etc/pythia/onchain-live-ack`, mode 600 (with `limits=wallet` the four `max_*` lines do not apply; they are
within the alpha maxima so the file stays valid without it):

```
mode=alpha
books=onchain_longterm
mints=SOL,USDC,BTC,ETH
book_usd=45
max_total_usd=100
max_trade_usd=25
max_daily_loss_usd=25
max_convert_usd=100
limits=wallet
expires=2027-01-20
on_kill=hold
I accept that I can lose all of it
```

`/etc/pythia/onchain-live.env`, mode 600, without Sender, its tip or a Jupiter key:

```
PYTHIA_ONCHAIN_LIVE=1
PYTHIA_ONCHAIN_KEYPAIR=/etc/pythia/onchain-keypair.json
PYTHIA_ONCHAIN_RPC=https://api.mainnet-beta.solana.com
```

Then: send 0.5 SOL to the wallet; in the app's Wallet tab swap about 0.465 SOL into USDC (four converts of up to a
quarter of the wallet each; at least 0.035 SOL stays); set the master share to 100 % and press Start (the control file
says 50 % and paused, from 2026-10-23); run `live_exec simulate` and `check` (docs/ONCHAIN-STAGE2.md, section 7,
step 7) and start `pythia-onchain-live` (step 9). The book trades on its current signal, then once per new one. `expires` at most 90 days
ahead: renew it before 2027-01-20.

## Notes

- Not convincing evidence: tsmom1 beat the ETF token from 2024 on drawdown-matched terms but its lead is within
  noise; a calm alternative is holding SPYx or a real S&P 500 ETF at a broker (S2's recommendation). The
  2020 to 2023 rows are where the rule was picked; read the 2024 to 2026 rows.
- The paper twin pays the fee cap on every swap (conservative); live pays what lands, usually far less.
- A failed swap (slippage) costs its fee only; the book tries again with the next day's signal.
