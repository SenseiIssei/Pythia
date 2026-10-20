# pump.fun in real time (X8)

PAPER ONLY. Nothing in `lab.pumpfun_rt` holds a wallet, reads a key, signs or
sends anything; every buy and sell is arithmetic on the recorded curve,
written to a paper ledger, and a test checks the package for any of it. Real
money is not this study's question: the owner's rule is real money only after
active and consistent profit on paper, and only he decides.

Pre-registration: `results/pumpfun_realtime_plan.md` (committed before any
rule or model was computed on the record). Code: `lab/pumpfun_rt/`. Server:
`research/ops/README.md`, "Real-time pump.fun lab".

## Why

The 5-minute watcher (`lab.paper.pumpfun`, `results/experiments.md` section 4)
bought every graduation it saw and lost badly in its first five days (1,209
closed, median -96 %, 61 rugs, hit rate 11 %); its filtered books barely
traded. It cannot see the part of pump.fun where most of the money changes
hands: most tokens are dumped within seconds of launch. This lab records every
token from its first transaction and asks, with honest fills, whether any
fast, very risky rule has an edge, and whether a model of the first seconds
and minutes helps.

## Data source and terms

| Option | Verdict |
|---|---|
| PumpPortal data websocket (`wss://pumpportal.fun/api/data`) | Not used. New-token and migration streams are free, but trades of a token (`subscribeTokenTrade`) cost 0.01 SOL per 10,000 events and need an API key linked to a funded wallet (their data API page, 2026-10-20). This project holds no wallet. |
| pump.fun's own frontend API | Not used: its terms (sections 6.1 and 21(h), as of 2026-10-08) forbid bots and other automatic access. |
| Solana RPC websocket, `logsSubscribe` on the programs | **Used.** The pump.fun program (`6EF8...F6P`) and PumpSwap (`pAMM...XEA`) log every event as an Anchor event; the layouts are in pump.fun's public IDLs (github.com/pump-fun/pump-public-docs). Read only, keyless. Default endpoint `wss://api.mainnet-beta.solana.com`; its documented limits are 40 connections, 100 requests per 10 s and 100 MB per 30 s per IP, and it says it is not meant for production. The collector uses five connections, one request each per connect, about 1 MB/s. `PYTHIA_SOLANA_WS` can point at a provider instead (its key then lives only in an env file on the server). |

What the stream turned out to be, measured on 2026-10-20:

- **Receive time is not event time.** A third of the curve trades arrive more
  than a second after the first notification of their slot, a fifth more than
  five seconds, PumpSwap trades later still, and some out of slot order.
  Every number here is therefore in chain time: events are ordered by slot and
  timed by the slot (the earliest receive time of that slot or any later one).
  Timing a late delivery by its own receive time would put a trade after our
  landing that happened before it, and hand us a stale, better price.
- **Connections drop** every minute or two (close code 1006 with websocket
  pings, so no pings are sent; liveness is a 90 s receive timeout). Each
  program is streamed over several connections side by side, duplicates
  dropped by signature; a gap is written only when every connection of a
  program is down at once, and every paper trade or model row that overlaps a
  gap is left out.
- **Completeness.** In short tests a connection to the default endpoint
  delivered nearly every curve trade while it was connected (3 to 5 of about
  2,000 trades' slots did not chain up); `solana-rpc.publicnode.com` delivered
  about 60 % of the same transactions and is not used. Against a separate
  capture the collector's record missed 107 of 4,174 trades (2.6 %), most
  likely around the frequent reconnects. On the record about 1 % of curve
  slots do not conserve SOL (the trades received for a token in a slot do not
  add up to its next state), and 31 % of plain curves have at least one such
  slot; the engine counts them, takes the received state (the next trade's
  reserves are absolute, so the error does not carry on), and every paper
  trade whose hold spans one is marked "broken"; the report shows each rule's
  mean with and without them. They make no material difference so far. A paid
  or dedicated endpoint would remove most of this; the owner decides whether
  that is worth it.
- **Universe.** About 45 % of new tokens are plain SOL curves. The rest are
  quoted in another token (USDC, stock tokens, other pump.fun tokens) or run in
  "mayhem mode" (fee-free trades with virtual reserves that jump without a
  trade); neither is traded or modelled.
- **Metadata** (socials, description) was planned as a feature, but the
  public IPFS gateways answered 429 or a service-worker page, and a third of
  the uris point at a launch tool's own host. The uri's kind (an IPFS upload
  as pump.fun's site does it, or a launch tool's host) is a feature instead.
- **The dev.** In about a fifth of creations a launch tool names a creator
  other than the wallet that pays; the dev buy then comes from the payer. "The
  dev" is both.
- **The pool at migration** opens with about 67 of the 85 SOL the migration
  event names (the migration fee); a pool's state is taken only from its own
  trades.

## Execution model (we are not first)

| Step | Model |
|---|---|
| Signal | the slot time of the event that makes it (a creation, a trade, a checkpoint) |
| Landing | signal + L, L lognormal with median 1 s, clipped to 0.4 to 3 s (an ordinary RPC sender, no bundles), seeded per rule, token and leg |
| Fill | the curve (or, after migration, the pool) after every trade received before the landing; curve arithmetic gives the slippage; the token's own fee (protocol plus creator, 1.25 % at the time of writing) on top of a buy and off a sale; a base fee plus 0.001 SOL priority fee per transaction |
| Our impact | our trade does not move the recorded curve, so the price impact is paid twice, which errs against us |
| Failed buy | the price at landing more than 30 % above the signal's, or the curve completed first: only the fee is lost |
| Sale | always fills, at whatever the curve or pool pays when it lands: a dump before our sale lands is ours |
| Stress | every rule also at doubled latency (0.8 to 6 s) and at tripled priority fee |

The signal is timed at the fastest notification of its slot. A bot on this
same public stream would often see the trade seconds later; L is meant to
cover detection and sending, and the doubled-latency case is the check.

## Rules and the model

As registered: 22 rules in five families (snipe at creation, first-seconds
pressure, momentum, pre-migration, post-migration), each with two exit sets
(take profit, stop loss, time stop), stake 0.1 SOL, at most 50 open per rule;
the model filter on the in-sample pick is the 23rd trial. The model predicts,
from features known at 3 s to 5 min after creation, whether the dev dumps
within 60 s, whether the curve completes within 6 hours, and whether a paper
round trip over 30 s or 5 minutes wins after costs; LightGBM with isotonic
calibration, purged walk-forward against the base rate and a logistic
baseline. Details and the bar: the plan.

## Results so far

**Little data: 2 hours 15 minutes of record**, collected on the PC
(2026-10-19 23:04 to 2026-10-20 01:19 UTC; the PC then slept), not yet on
the server. Nothing below is evidence of anything; every rule fails the bar,
most of them on size alone. The full run is `results/pumpfun_rt.md`.

| | |
|---|---|
| Tokens created | 3,459, of which 1,495 on plain SOL curves (43 %) |
| Curve trades | 315,357 (94,804 on plain curves) |
| Curves completed | 76 (about 2 % of all tokens, 2 to 5 % of the plain ones) |
| Gaps | 25, 5.6 minutes in all (restarts of the PC run included) |
| Slots that did not conserve | 1,093 of the plain curves' trades' slots, 31 % of plain curves have at least one |
| Split | in sample to 2026-10-20 00:11 UTC, out of sample after |

Out of sample (about 70 minutes), 0.1 SOL a trade, every cost in:

| family | best rule out of sample | trades | mean per trade | median | hit rate | P&L SOL | doubled latency | tripled priority fee |
|---|---|---|---|---|---|---|---|---|
| A snipe every token | A_all_x1 | 600 | -4.8 % | -5.1 % | 12 % | -2.88 | -4.5 % | -8.8 % |
| A snipe, dev buy 0.5 to 5 SOL | A_dev_x1 | 295 | -5.1 % | -5.3 % | 20 % | -1.50 | -5.6 % | -9.1 % |
| A snipe, creator with a completed curve | A_cmig_x1 | 8 | +7.9 % | -5.0 % | 38 % | +0.06 | +11.1 % | +3.9 % |
| B pressure at 3 s | B_w3_x1 | 107 | -9.0 % | -11.9 % | 20 % | -0.97 | -9.2 % | -13.0 % |
| B pressure at 10 s (the in-sample pick) | B_w10_x1 | 42 | -11.4 % | -13.7 % | 31 % | -0.48 | -12.7 % | -15.4 % |
| C momentum 20 buyers in 60 s | C_20in60_x1 | 41 | -14.3 % | -27.0 % | 22 % | -0.59 | -14.0 % | -18.3 % |
| D curve past 90 % | D_p90_x2 | 2 | +61.3 % | +61.3 % | 100 % | +0.11 | +60.4 % | +57.3 % |
| E pool, migration + 60 s | E_d60_x1 | 12 | -2.3 % | +1.4 % | 50 % | -0.03 | +0.3 % | -6.3 % |

What the first hours say, with every caveat of 70 minutes:

- **Sniping pays the costs and little else.** Buying every plain token as
  soon as its creation is visible, 0.4 to 3 s later, and selling within 15 s
  loses 5 % per trade with a median of exactly the round-trip cost (1.25 %
  fee a side, 0.001 SOL priority fee a side on a 0.1 SOL stake, the impact
  paid twice): most tokens do not move in the first 15 s after we land, and
  the dev sold during 24 to 58 % of the holds.
- **Momentum entries are worse, not better.** Waiting for buyers (B, C) means
  buying after the first wave; the median trade loses 12 to 40 %. The live
  shadow book ran the default rule `C_20in60_x1` on the stream for the same
  two hours: 113 closed paper trades, 22 winners, mean -10.9 %, median
  -25.2 %, -1.23 SOL on 11.3 SOL staked, best +135 %, worst -63 %.
- **Late-curve and post-migration entries are positive in a handful of
  trades** (D_p90 2 to 4 trades, A_cmig 8, E_d60 12). That is not a result;
  these are the families to watch as the record grows.
- **Failed buys** were common where it matters: 162 buys arrived after the
  curve had completed, 61 above the 30 % slippage limit.
- **The model** (rows at 3 s to 5 min, purged walk-forward, 3 to 4 folds) is
  "not useful" on every label by the registered rule. It does rank "the dev
  dumps within 60 s" (AUC 0.76, Brier skill +0.19 against the base rate of
  27 %, but it beats the logistic baseline in 1 of 3 folds only), and the
  round-trip labels (win rate 4 to 5 %) at AUC 0.64 to 0.71 without beating
  the base rate's Brier score. The strongest inputs are the last 10 s of net
  flow, whether the metadata was an IPFS upload (pump.fun's site) or a launch
  tool's host, the dev buy, the first five buyers' share, and market activity.
  The registered filter let every entry of the pick through (same 42 trades),
  so it changed nothing.
- **Deflation** is not computable under 5 days; the pool now stands at 1,230
  trials (907 hand, 300 factory, these 23), a noise bar of Sharpe 2.85.

The bar needs 14 days and 300 out-of-sample trades per rule; until the
collector has run on the server for that long, the report says "too early".

## What would be needed before anyone even considered real money

Not a decision this study can make; the owner decides, and only after active
and consistent profit on paper. What the evidence would have to show first:

1. A rule that clears every registered gate out of sample: mean net return per
   trade above 0 with its hour-block bootstrap band above 0, 300 or more trades
   over 14 or more days, still positive at doubled latency and tripled
   priority fee, not carried by five trades, positive on 60 % of days, and a
   deflated Sharpe p above 0.95 against the lab's whole pool (now about 1,500
   trials).
2. The same rule positive with and without the trades on broken slots.
3. Then 30 days of the live shadow book inside the replay's range, and at
   least 60 days of consistent paper profit in all.
4. Evidence that the fill model is not flattering: our own latency measured,
   not assumed (a paper study cannot measure it), and the fills of the fastest
   competitors understood. The fastest bots land in the creation block; this
   model lands 0.4 to 3 s later by construction.
5. Even then a tiny stake, loss limits, and the owner's explicit decision. A
   token can go to zero between two slots; every position must be sized as a
   total loss.

What is known today points the other way: the fee is 1.25 % a side plus the
priority fee, the dev is often the first seller, and a sale lands into
whatever is left.

## The trading pipeline (X10, 2026-10-20)

The owner asked for pump.fun to be "implemented": a complete, automatic
pipeline that could one day trade real money, built now with real money
locked. Pre-registered in the plan's addendum 2 before anything below was
computed.

**What was built** (`lab/pumpfun_rt/`):

| Part | Module | What |
|---|---|---|
| Pipeline | `pipeline.py` | signal, filter, sizing (0.1 SOL, never over 2 % of the curve's SOL), risk limits (5 open, 0.6 SOL exposure, 1 SOL daily loss stop, kill switch), entry with a cost limit, exits: take-profit ladder, stop, trailing stop, dev sell, liquidity pull, risk model, time stop. One decision layer; `PaperExecutor` and `LiveExecutor` take the same orders and report through the same four calls, so a paper book does what a live one would, its limits included |
| Strategies | `pipeline.STRATEGIES` | 8 trials: snipe with dev buy, snipe of creators with a completed curve (with and without a model filter), pressure at 10 s, momentum with a model filter and a risk-model exit, the curve past 80 % with a smart early buyer, past 90 %, the pool 60 s after migration. The pool counts 31 trials here |
| Wallets | `wallets.py` | point-in-time reputation: early buys, how many completed, flips; smart money, flippers, repeat dumpers |
| Categories | `categorize.py` | each day's new names into six categories by Claude Haiku 5.5 (a data provider, through the engine's metered endpoint; cached per mint and per name, usable from the moment the answer was written) |
| Models | `model.py`, `retrain.py` | five new labels for fast exits (the dev or a top-10 holder sells a quarter within 10 or 30 s; the price 10 s, 30 s, 2 min after a landing above it), every label tried with base, wallet and category features in a purged walk-forward; a set is used only where it wins out of sample. Daily, after the study |
| Readiness | `study.py` | per strategy, the owner's gate: 14+ days, 300+ trades out of sample, positive with and without broken slots, every gate, 30+ days of the live paper shadow inside the replay's band |
| Live | `live_exec.py`, `txbuild.py`, `live_service.py`, `wallet.py`, `measure.py` | LOCKED. Plain pump.fun and PumpSwap buy and sell instructions to a public RPC, only in a service the owner starts by hand; refuses unless the owner switches it on, makes his own wallet with the wallet tool, confirms in writing, the IDLs match and no kill switch is set; then either the strategy is ready (full) or, for the owner's small TEST (at most 2 SOL in all, 0.5 a day, 0.05 a trade), a mainnet simulation passed within 24 hours. The test measures our own landing latency, slippage and fees against the fill model. Hard caps in code. See `docs/PUMPFUN-LIVE.md` and `research/ops/README.md`, "Live trading (locked)" |
| Cards | `card.py` | the daily card (paper P&L per book, the bar, the models, readiness, the live state) after the retrain; a paper winner over +200 % at once (at most one an hour); every live fill or failure, if live were ever on |

On terms: pump.fun's terms forbid bots and automatic access on its website
and API. The pipeline uses neither: it reads the public chain and would send
the programs' own public instructions to a public RPC endpoint, which those
terms do not cover. No bundles, tips, private relays or front-running of
other users; the executor refuses such endpoints. The owner decides with
that knowledge.

**First numbers: 3 hours of the server's record** (2026-10-20 16:40 to 19:37
UTC, 5,919 tokens, 2,910 on plain curves, 499,358 curve trades, 102
completions; 51 gaps, 7 minutes), split at 18:08 UTC, so about 90 minutes
out of sample. Nothing here is evidence; every rule and strategy fails the
bar on size alone.

| strategy | trades out of sample | mean | P&L SOL | how it exited |
|---|---|---|---|---|
| P_snipe_dev | 0 (97 in sample, -7.9 %) | n/a | 0 | the daily loss stop ended its day in sample |
| P_snipe_cmig | 3 | +6.8 % | +0.02 | 2 pulls, 1 dev sell |
| P_press10 | 24 | -19.0 % | -0.46 | 14 pulls, 6 time, 3 dev sells |
| P_mom_model | 29 | -6.5 % | -0.19 | 18 pulls, 6 time, 3 risk model |
| P_p90 | 15 (6 failed buys) | -23.8 % | -0.36 | 7 stops, 4 pulls, 3 trailing, 2 rugs |
| P_p80_smart | 1 | -8.2 % | -0.01 | |
| P_pool60 | 6 | +27.4 % | +0.16 | 3 trailing, 2 take, 1 stop |
| P_cmig_model | 0 | n/a | 0 | the filter let nothing through |

For comparison the registered rules on the same 90 minutes: sniping every
token -5.4 % per trade (1,239 trades), the in-sample pick C_20in60_x2 -22.6 %
(52), the pool rules E_d0_x1 +29.7 % (6) and E_d60_x1 +17.7 % (8). The
pipeline's books replayed through the shadow (the collector's own code path)
over the whole three hours: P_snipe_dev 100 closed, -8.3 % per trade; P_press10
116, -5.7 %; P_p90 25, -13.6 %; P_pool60 19, -6.4 %; the old pick C_20in60_x1
131, -11.6 %.

What the first hours say:

- **The exits act.** The liquidity-pull and dev-sell exits fire on most
  early-curve positions, at the slot of the sale, and the losses there are
  smaller than the registered rules' with plain stops (P_mom_model -6.5 %
  against C_20in60 at -22.6 %), but still losses. An early holder of 2 % of
  the supply selling is common, so "pull" is the usual way out.
- **Only the pool stays positive**, in a handful of trades, as it did on the
  PC's record. It is the family to watch.
- **The daily loss stop binds**: a snipe book loses its 1 SOL before noon and
  stops, exactly as live would.
- **The models** (4,481 rows after gaps, 3 folds) are "not useful" on every
  label by the registered rule. The exit models rank well (P(the dev or a
  top-10 holder sells within 10 s) AUC 0.81, Brier skill +0.22, beating the
  logistic baseline in 2 of 3 folds; the price-up labels AUC 0.66 to 0.78),
  but the logistic baseline is as good or better. Wallet features did not win
  on any label yet (the reputation needs days of history); the categories
  have no answers yet (the first batch runs on the server).

Everything waits for the record to grow (about 100,000 tokens a day). The
daily card shows each strategy's progress toward the owner's live gate.
