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
- **Completeness.** A single connection to the default endpoint delivered
  every curve trade in two 2-minute tests (the reserves chain up trade by
  trade); `solana-rpc.publicnode.com` delivered about 60 % of the same
  transactions and is not used. On the collector's record about 1 % of
  curve slots do not conserve SOL (the trades received for a token in a slot
  do not add up to its next state); the engine counts them per token, takes
  the received state, and every paper trade whose hold spans one is marked
  ("broken"); the report shows each rule's mean with and without them.
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

FIRST_RESULTS

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
