# E1: slippage limit and tip for the pump.fun buys (2026-10-27)

Code `lab/experiments/execution_e1.py`. PAPER ONLY: a rule written down; the live bot, its bound, its fees, its
sizing and every paper book are unchanged. Reproduce: `python -m lab.experiments.execution_e1` (live part, seconds)
and `--replay` (R1's replay at every limit, about 12 minutes and 2 GB on the eight recorded days; the heavy lock).

## Shrunk after the review

The first brief (a cost map for 40 to 1,000 EUR by hour and weekday, cheaper rebalance hours, slicing and a no-trade
band for the paper books) was dropped: Jupiter swaps cost about 2 bps already and pump.fun's pool fee cannot be cut.
What is left to choose is how far a buy may run past its quote before it fails (the slippage limit, live 60 % since
2026-10-23) and what a transaction pays to land (priority fee and the Helius Sender tip). A loose limit is also what a
sandwich lives on: whoever buys in front of us may push the price up to the limit.

## How

- **The live buys**: the 142 pool buys of the live bot that filled and closed (2026-10-22 to 24), each with its run
  past the quote (the tokens the order asked for over the tokens it got, less 1). The live bound fails a buy exactly
  when the run is above the limit, so for a tighter limit the counterfactual is exact on these buys: a buy over it
  would have failed with 6040 and paid the median 6040 fee (0.000249 SOL) instead of its trade. The 8 buys that failed
  with 6040 and the 8 skipped before the send fail under any tighter limit too.
- **The pick, set before looking**: the best mean P&L per buy order among the limits that miss at most 10 % of the
  winners' P&L (good fills) and beat 60 % in both chronological halves; else keep 60 %.
- **R1's replay**: the realistic P_pool0_wait (the live latency drawn per trade, fills at the first recorded trade
  after the landing, the pre-send skip and 6040) at 0.1 SOL on every signal of the record 2026-10-20 to 27, one book
  per limit with the same latency draws. Many more trades, but paper: R1 found it still flatters the mean.
- **Fee and tip**: the 223 landed transactions since the dynamic priority fee, fee against send to landing.
- **Sandwiches**: the bot's own trades found on the recorded PumpSwap stream (117 of its 284 pool fills), another
  wallet trading the same side just before ours in our slot and the other side within 2 slots after.

## The answer

**A 20 % limit instead of 60 % would have cut the live loss per buy order by almost two thirds and missed only 3 good
fills.** On the 142 live buys: -0.0027 SOL per order at 60 % (-1.6 % of the stake per filled buy), -0.0010 SOL at
20 % (-0.45 %); 13 buys dropped, 10 of them losers (0.39 SOL of losses avoided), 3 winners (6 % of the winners' P&L);
better in both halves, 90 % interval of the gain +0.00008 to +0.00348 SOL per order. Buys that ran more than 10 %
past the quote won 30 % of the time (median -18 %), the ones 0 to 5 % past it 68 %. 30 % misses no winner but gains less.

**R1's replay agrees in direction.** Every limit tighter than 60 % made more per signal; 20 % made +9.4 SOL against
+8.6 SOL on 1,682 signals (+10 %) and missed 20 of the 60 % book's winning coins, 2 % of its winners' P&L. Tighter
still (5 to 15 %) made a little more in the replay but missed 5 to 10 % of the winners' P&L and lost the live
halves test (10 % and 15 % have intervals through 0 on the live buys). 100 % was no better than 60 %.

**The tip and priority fee buy nothing measurable.** Send to landing is about 0.52 s (p90 0.75 to 0.78 s) whether the
fee was 0.00007 or 0.0003 SOL (Spearman -0.03, p 0.69); the buy's lateness is the decision (waiting for the coin's
creation), not the landing. At the live stake (0.103 SOL) a round trip's fee and tip cost 1.97 % with the old fixed
0.001 SOL priority, 0.31 % at the dynamic fee's median and about 0.15 % in the lowest third (0.00007 SOL).

**No sandwich found**: none of the 59 buys and 58 sales on the stream was sandwiched; 15 buys had another wallet
buying before ours in our slot (other bots on the same migration, not traded back within 2 slots). The stream did
not carry all our fills, so this is a sample, not a proof; a tight limit caps a sandwich anyway.

## The paper rule

For pool buys: **a slippage limit of 20 %** (the quote / 1.20, checked before the send as live), **a priority fee
from the low end of recent fees, at most 0.0001 SOL, and the Sender tip at its minimum (0.000005 SOL)**. Sales keep
their present limits (a protective exit must not fail). Nothing is switched: the live limit stays the owner's
`PYTHIA_PUMPFUN_BUY_TOL` (60 % by default), its priority fee and tip the owner's settings. Limits: 142 live buys over
two days, picked among 7 limits on them; the replay is paper. Worth re-running when the live bot has a week more.

<!-- generated below by lab.experiments.execution_e1; edit above this line only -->

Made 2026-10-27 11:30 UTC. Live pool buys that filled and closed: 142 (2026-10-22 22:05 to 2026-10-24 08:37 UTC); failed on their bound: 8 with 6040 (median fee 0.000249 SOL), 8 skipped before the send. Run past the quote: median +1.4 %, p90 +16.2 %, max +45.0 %.

### Trades by their run past the quote

| run | trades | mean return | median return | won |
|---|---|---|---|---|
| -100 % to +0 % | 36 | -3.0 % | -17.2 % | 39 % |
| +0 % to +5 % | 62 | +2.1 % | +16.9 % | 68 % |
| +5 % to +10 % | 21 | -3.0 % | +21.8 % | 52 % |
| +10 % to +20 % | 10 | -2.3 % | -8.6 % | 40 % |
| +20 % to +30 % | 10 | -7.0 % | -19.0 % | 30 % |
| +30 % to +60 % | 3 | -30.8 % | -21.5 % | 0 % |

### Each limit on the live buys (a buy over it fails and pays the 6040 fee)

| limit | trades | dropped | good fills missed | their P&L SOL (share of winners) | losses avoided SOL | P&L SOL | per order SOL | per filled buy, % of stake | vs live per order (90 %) | half 1, half 2 SOL |
|---|---|---|---|---|---|---|---|---|---|---|
| 5 % | 98 | 44 | 18 | +0.6218 (31 %) | 1.0508 | -0.0085 | -0.00005 | +0.09 % | +0.00265 (-0.00066 to +0.00608) | +0.1008, +0.3173 |
| 10 % | 119 | 23 | 7 | +0.2462 (12 %) | 0.5214 | -0.1571 | -0.00099 | -0.32 % | +0.00171 (-0.00020 to +0.00373) | +0.1301, +0.1393 |
| 15 % | 125 | 17 | 5 | +0.1945 (10 %) | 0.3986 | -0.2267 | -0.00143 | -0.78 % | +0.00127 (-0.00052 to +0.00314) | +0.0777, +0.1222 |
| 20 % | 129 | 13 | 3 | +0.1181 (6 %) | 0.3891 | -0.1588 | -0.00100 | -0.45 % | +0.00169 (+0.00008 to +0.00348) | +0.0837, +0.1841 |
| 30 % | 139 | 3 | 0 | +0.0000 (0 %) | 0.1615 | -0.2658 | -0.00168 | -0.93 % | +0.00102 (+0.00019 to +0.00223) | +0.0000, +0.1608 |
| 45 % | 142 | 0 | 0 | +0.0000 (0 %) | 0.0000 | -0.4265 | -0.00270 | -1.58 % | +0.00000 (+0.00000 to +0.00000) | +0.0000, +0.0000 |
| 60 % | 142 | 0 | 0 | +0.0000 (0 %) | 0.0000 | -0.4265 | -0.00270 | -1.58 % | +0.00000 (+0.00000 to +0.00000) | +0.0000, +0.0000 |

Picked by the pre-set rule (best per order, at most 10 % of the winners' P&L missed, better than 60 % in both halves): **20 %**.

### R1's realistic replay of P_pool0_wait (2026-10-20 to 2026-10-27, 0.1 SOL, every signal, same latency draws, 0.000214 SOL a transaction)

| limit | signals | trades | skipped before the send | 6040 | P&L SOL | per signal SOL | mean return | median return | good fills of the 60 % book missed (share of its winners' P&L) |
|---|---|---|---|---|---|---|---|---|---|
| 5 % | 1682 | 1347 | 231 | 73 | +10.217 | +0.00607 | +7.6 % | +13.4 % | 109 (10 %) |
| 10 % | 1682 | 1464 | 148 | 39 | +9.824 | +0.00584 | +6.7 % | +13.0 % | 55 (5 %) |
| 15 % | 1682 | 1525 | 108 | 18 | +9.761 | +0.00580 | +6.4 % | +12.5 % | 27 (2 %) |
| 20 % | 1682 | 1545 | 93 | 13 | +9.424 | +0.00560 | +6.1 % | +12.2 % | 20 (2 %) |
| 30 % | 1682 | 1576 | 65 | 10 | +9.025 | +0.00537 | +5.7 % | +11.6 % | 8 (1 %) |
| 45 % | 1682 | 1597 | 50 | 4 | +8.857 | +0.00527 | +5.5 % | +10.8 % | 2 (0 %) |
| 60 % | 1682 | 1613 | 36 | 2 | +8.580 | +0.00510 | +5.3 % | +9.9 % | 0 (0 %) |
| 100 % | 1682 | 1621 | 28 | 2 | +8.685 | +0.00516 | +5.4 % | +9.9 % | 0 (0 %) |

### Fee and tip

Landed transactions since the dynamic priority fee: 223, Spearman of fee and send to landing -0.03 (p 0.69).

| fee tercile, SOL | transactions | median fee | send to landing, median ms | p90 ms |
|---|---|---|---|---|
| 0.000008 to 0.000110 | 75 | 0.000073 | 520 | 778 |
| 0.000111 to 0.000215 | 74 | 0.000155 | 522 | 773 |
| 0.000215 to 0.000957 | 74 | 0.000305 | 524 | 748 |

A round trip's network fee and Sender tip at the live median stake 0.103 SOL: +1.97 % with the old fixed 0.001 SOL priority, +0.31 % at the dynamic fee's median 0.000155 SOL (tip 0.000005).

Sandwich check on the recorded stream (our own rows found there): buys 59, 15 with another wallet buying before ours in our slot, 0 sandwiched; sales 58, 13 with a sale before ours, 0 sandwiched.
