# Live twin: every live pump.fun trade replayed through the realistic executor. Pre-registration

Registered 2026-10-29 and committed before any twin, count, mean or band of this study was computed. Brief of the
training plan on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows, P1's taint rule (`realistic.tainted`) and the
readiness ladder (`lab.ops.ladder`). Paper only and read only on everything live: nothing a live bot, its sizing, a
wallet or the engine reads changes; `live.py`, `live_exec.py`, `live_service.py` and every wallet file are not
touched. Numbers seen before this file: P2's (`results/pumpfun_selection_gap_p2.md`: paper minus live +18.9 points
a trade, +15.7 of it on the same coins, 101 of 149 live trades without a paper twin), the review's (149 live trades,
mean -2.6 % a trade) and the count of stream gap rows on 2026-10-22 to 24 (1,089 PumpSwap, 224 pump, typical length
5 s), looked at to fix the gap rule below.

## The question

P2's same-coin gap was mostly the ideal paper model before 2026-10-24 01:43 UTC, and two thirds of the live trades
had no paper twin at all. Here every live trade gets one: the same coin, the same signal time and the same rule,
replayed through `lab/pumpfun_rt/realistic.py`'s executor on the recorded stream. Live minus twin, per trade, says
how much realistic paper still flatters (or undersells) live on exactly the trades live made, and which step of a
trade it comes from.

## Inputs (read only)

- The live trades: `<data>/live/pumpfun_rt/ledger.csv`, all its closed trades of the live modes (test, full).
  `reports/pumpfun_rt/live_trades.json` shows the newest 100 of them (a subset, same fields); the ledger is the
  whole record of 149. Per trade: rule, coin, `signal_ms`, `land_ms`, `exit_ms`, `entry_price`, `exit_price`,
  `stake_sol`, `ret`.
- The live orders: `orders.jsonl` (the buy as sent, its `limit_l` and `stake_l`), `measured.jsonl` (each fill's
  decision time `signal_ms`, the latency fit's input).
- The recorded stream: `<data>/pumpfun_rt/{creates,trades,amm,other,meta}`, every recorded day from the first to
  the day of the last live exit, each event timed by its slot as `sim.day_events` does (`store.slot_times`, from
  every row of the day), only the live trades' coins kept, and every gap row.

## The twin

- **Signal**: at the live trade's `signal_ms`, on the stream's clock, the live trade's rule as a pipeline strategy
  with its filters and wait taken off (the live bot's signal already passed them; `wait_pool_s` dropped, so the
  twin buys at the live signal time or not at all), its exits unchanged, on the coin's recorded state at that time.
- **Stake**: the live sizing at that time is the stake the live bot sent: the buy order's `stake_l`, else its
  `limit_l / (1 + SLIP_TOL)` (`live_exec.pool_buy_amounts`). The pipeline's 2 % depth cap applies as it did live.
  No paper wallet, no slot or exposure limit: one twin per live trade.
- **Execution**: `realistic.RealExecutor` and `realistic.Book` unchanged: latency drawn per (rule, coin, side) from
  the fit, the fill at the first recorded trade at or after the landing with the stake's own impact, the live pool
  bound and pre-send check, the 6040 on landing, the drawn failures, the network fee and the Sender tip.
- **The fit, out of fit**: the twin of a live trade signalled on UTC day D runs on `realistic.fit` of every live
  `measured.jsonl` row whose UTC day is not D (the whole record less D, no FIT_DAYS window; a side with fewer than
  MIN_ORDERS fills takes the fallback as in the daily job). Leave one day out: a day is never judged by a model
  fitted on its own orders. One book per judged day on one engine, each with its own fit.

## No twin, with its named reason

In this order, a live trade has no twin when:

1. **coin not recorded**: the stream holds no state of the coin at the signal (no creation row of it in the
   replayed days);
2. **no pool state in the record** (pool rules): the coin had no recorded pool reserves at the signal;
3. **stream gap**: a gap row of the program the trade trades on (PumpSwap for a pool trade, pump for a curve trade)
   covers one of the moments the replay needs, on either side: the signal, a buy landing to FILL_WAIT_MS after it,
   the last sale's decision, the last sale's landing to FILL_WAIT_MS after it; or the gaps of that program cover
   10 % or more of the window from the signal to the later of the two sides' last sale landings;
4. **P1 taint**: the twin's closed row is `realistic.tainted`;
5. **twin open at the end of the record**.

The twin's own outcomes are twins, not misses: a buy that fails (drawn failure, 6040, the pre-send skip "price ran
away") is a twin whose return is its fee over the stake (0 for the skip), and a skip of the pipeline at the signal
other than the two above (no depth, nothing to buy, not a plain SOL pool or curve) is a twin that did not buy
(return 0, counted under failed buys).

## Per trade: live minus twin and its parts

Each side: E the entry price, X the exit price (SOL per token: the ledger's `entry_price` and `exit_price` live,
the book's `cost_l` and `proceeds_l` over the tokens bought for the twin), g = X / E - 1 the gross price return,
ret the side's own return after all costs. m(t): the coin's price at the first recorded trade at or after t (the
state after it; else the last before t). Live minus twin, ret_L - ret_T, in points a trade (x 100), splits exactly
in this order:

- **entry latency** = g(E_1, X_T) - g(E_T, X_T), with E_1 = E_T m(land_L) / m(land_T): the twin's fill moved to
  the live landing;
- **entry price** = g(E_L, X_T) - g(E_1, X_T): live's fill against that;
- **exit decision time** = g(E_L, X_1) - g(E_L, X_T), with X_1 = X_T m(xdec_L) / m(xdec_T), xdec the last sale's
  decision time (live: the last sell fill's `signal_ms` in `measured.jsonl`, else its last sent sell order);
- **exit price** = g_L - g(E_L, X_1): live's sale against the twin's moved to the live decision;
- **fees** = (ret_L - g_L) - (ret_T - g_T): network fees, the tip, the rent, each side's stake definition, what
  the prices do not explain;
- **failed buys**: a twin that did not buy carries the whole difference here, every other part 0.

The parts add up to the total per trade, so their means add up to the mean (within rounding).

## The numbers

- Twins found, and every miss by its reason and rule (the judge: at least 120 of 149, or every miss named).
- Live minus twin over the twinned trades: mean, median, a day-clustered 95 % band (percentile bootstrap over UTC
  days of the signal, 2,000 draws, seed 0; the mean of the pooled trades of each draw), and the mean of each part
  with its own day-clustered band; their sum against the total.
- Split by UTC day and by rule (P_pool0_wait, P_cmig_model, P_pool0): n, mean, median and the parts.
- A check, reported next to it only: the same over the trades whose window has no gap of their program at all.
- With few days the day-clustered band is coarse (a bootstrap over k days has at most C(2k-1, k) distinct draws);
  it is reported as it comes.

## The haircut

If the day-clustered band of the mean excludes 0, the haircut paper books would need is the mean live minus twin
in points a trade (negative: paper above live, take that off each paper trade). It is proposed in the report only;
no book, gate, ladder or live file reads it.

## R6 and the out-of-fit rule

R6's windows (in sample to 2023-12-31, validation to 2026-06-30, lockbox from 2026-07-01) are the daily panels'.
The pump.fun record starts 2026-10-20, all of it after the lockbox's start; this is a measurement of execution on
the live bot's own trades, no strategy is searched or promoted, and the out-of-fit rule here is the leave-one-day-out
refit above.

## Trials

Five in R5's registry, family pumpfun, counted only (no Sharpe, no DSR), registered before the first number:
`pumpfun:live_twin:total`, `pumpfun:live_twin:components`, `pumpfun:live_twin:by_day`, `pumpfun:live_twin:by_rule`,
`pumpfun:live_twin:no_gap`. The report: `python -m lab.pumpfun_rt.live_twin` writes `results/pumpfun_live_twin.md`.
