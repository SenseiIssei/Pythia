# pump.fun speed at release (Y3)

PAPER ONLY. Nothing here holds a wallet, reads a key or sends a
transaction. Fills are the recorded curve's arithmetic; the fast path signs
with a fake signer and sends nothing.

Pre-registration: `results/pumpfun_speed_plan.md` (120 trials, committed
before any tier was computed) and its addendum 1 (tier `S0r`, 15 more
trials, written after the first run and disclosed as such). Code:
`lab/pumpfun_rt/latency.py`, `speed.py`, `fastpath.py`, `geyser.py`; the
gate in `live_exec.py`, tips in `txbuild.py`. Data: a read-only copy of the
server's record, 2026-10-20 16:40 to 22:11 UTC (5 h 31 min, 11,258
creations, 941,495 curve trades, 101 gaps), and 149 creation blocks read once
from the public RPC.

The owner asked for the snipes to be "always in right at release". Short
answer: **speed does not pay at any speed this project can reach.** It pays
only in one place, the very front of the creation slot, and that place is
taken by bundles that include the creator's own transaction, which this
project does not send.

## 1. How late we are today

Our receive time of each creation against the chain's block time (the
programs' block timestamps fitted against the slot number; slots are 216 ms
now, not 400):

| | p10 | p25 | p50 | p75 | p90 | p99 |
|---|---|---|---|---|---|---|
| behind the block | 2.4 s | 6.2 s | 14.9 s | 28.8 s | 43.7 s | 88.9 s |
| in slots | 11 | 29 | 69 | 133 | 202 | 411 |
| newer slots already received (no clock needed) | 0 | 0 | 27 | 93 | 163 | 377 |
| curve trades behind the block | 2.5 s | 6.4 s | 15.4 s | 29.7 s | 45.5 s | 95.3 s |

| seen | in the creation slot | +1 | +2 | +3 to 4 | +5 to 9 | +10 to 49 | +50 or later |
|---|---|---|---|---|---|---|---|
| creations | 1.2 % | 0.6 % | 0.7 % | 1.6 % | 5.1 % | 30.2 % | 60.6 % |

3.7 % within a second, 8.4 % within 2 s, 20.6 % within 5 s. Every hour looks
the same (medians 11.2 to 19.4 s). The 1.2 % "in the creation slot" is the
clock's uncertainty (the block timestamp has whole seconds and the cluster's
clock is not ours), not real: a confirmed notification cannot arrive inside
its own slot.

Why: the public endpoint delivers whole slots late. A two-minute probe of it
against its own slot notifications (`latency.py probe`) had its confirmed log
notifications a median 105 slots (about 23 s) behind its own tip, and
"processed" 47 slots behind. The collector is not the bottleneck (2.7 % of a
CPU). The paper model's assumption (we land 0.4 to 3 s after the slot) was
therefore generous by an order of magnitude for anything that reacts to a
creation.

## 2. Speed tiers

Every plain SOL curve token, 0.1 SOL, bought at nine speeds and sold with
three exits; every cost in (the token's fee a side, base and 0.001 SOL
priority fee per transaction), no tip charged (the break-even tip is what the
tip may cost). Out of sample (the record's second half, 2 h 46 min), filter
`all` and `dev` (dev buy 0.5 to 5 SOL); failed buys count as their fee:

| tier | lands | all: ladder | all: hazard | all: 15 s | dev: ladder | dev: hazard | break-even tip (best) |
|---|---|---|---|---|---|---|---|
| `S0f` | creation slot, first after the creation | +16.7 % (2,200) | +33.0 % (1,319) | +13.7 % | +31.8 % | +38.6 % | 0.039 SOL |
| `S0r` | creation slot, right behind the run after it | +1.2 % (1,900) | +6.4 % (1,019) | +0.4 % | +4.7 % | +7.2 % | 0.007 SOL |
| `S0b` | creation slot, back | -3.7 % (1,737) | -1.9 % (866) | -3.7 % | -3.2 % | -1.8 % | none |
| `S1` | + 1 slot | -4.4 % | -2.9 % | -4.2 % | -3.9 % | -2.8 % | none |
| `S2` | + 2 slots | -4.6 % | -3.1 % | -4.5 % | -4.4 % | -3.0 % | none |
| `T1` | 1 s | -4.7 % | -3.6 % | -4.7 % | -4.8 % | -3.8 % | none |
| `T2` | 2 s | -4.6 % | -3.7 % | -4.3 % | -4.4 % | -4.1 % | none |
| `NOW` | our measured delay + 2 slots | -4.4 % (1,386) | -3.4 % | -3.9 % | -3.7 % | -4.4 % | none |
| `LM` | the paper model's 0.4 to 3 s | -4.5 % | -3.7 % | -4.7 % | -4.9 % | -3.7 % | none |

(Trades in brackets where they differ much; the hazard books keep fewer
trades because a 30-minute hold overlaps a gap of the record more often and
is left out. Medians are -5.1 % (the round-trip cost) or -1.0 % (a failed
buy's fee) almost everywhere outside `S0f`. Hit rates: `S0f` 26 to 67 %,
`S0r` 13 to 31 %, `S0b` 6 to 15 %, the rest 3 to 10 %. Rugs, a loss of half
the stake or more: 0 to 12 per book. All 135 rows, the creator, clean-creator
and wallet filters included, are in `reports/pumpfun_rt/speed.md`; the
filters move the means by a point or two and change nothing below.)

What this says:

- **From one slot late to fifteen seconds late, speed is worth nothing.**
  `S1`, `S2`, `T1`, `T2`, `NOW` and `LM` all lose 3 to 5 % per trade, within a
  point of each other. Landing 200 ms after the creation instead of 15 s
  after it does not change the result, because the snipers of the creation
  slot have already moved the price and the curve then mostly falls.
- **The back of the creation slot loses too** (-1.8 to -3.7 %), and 22 % of
  its buys fail outright: the same-slot buyers lift the price more than the
  30 % cost limit allows.
- **Only the front pays, and it is not ours to take.** `S0f` makes +14 to
  +39 % per trade before any tip (filters `all` and `dev`); per token it is worth 0.003 to 0.010 SOL
  more than `S0b` on average, with a median of 0.000 to 0.005 SOL (most tokens
  do nothing either way, a few pay for all). But in the block sample 56 % of
  the outside buyers in a creation slot stand in an unbroken run directly
  behind the creation transaction: the creator's own bundle, or bundles that
  include the creator's transaction. A transaction of our own cannot be
  placed in front of them, and this project does not bundle anyone else's
  transaction. So `S0f` is out of reach by construction.
- **Right behind that run (`S0r`) is the reachable front, and it is thin.**
  +0.4 to +9.2 % per trade before tips (the hazard exit and the dev or clean
  filters best), a break-even tip of 0.0004 to 0.009 SOL per round trip. The
  later buyers of the creation slot bid (priority fee plus tips) a median
  0.0033 SOL for the best of them, 0.028 SOL at the 75th percentile and 0.060
  SOL at the 90th. To be ahead of them we must outbid them: in about half the
  slots that eats the whole edge, in a quarter it costs three times the edge.
  `S0r` is also optimistic: the record's run behind the creation is shorter
  than the block's in 21 % of the sampled slots (longer in 14 %), which puts
  us ahead of buyers that really were in the run.
- **And `S0r` needs us inside a 216 ms slot.** On today's feed 1.2 to 2.5 %
  of creations are even seen within two slots, and those figures are clock
  noise. Getting there needs shred-level data (Jito ShredStream or a
  provider's shred feed), a sender close to the leaders and a winning bid.

Too early by the lab's bar in any case: one day of record, under 3 hours out
of sample, no hour-block band (it needs 10 hours), far from 14 days and 300
trades per book. The means above are the first reading, not evidence.

**Verdict: no.** At every tier this project can reach (our own single
transactions, today's feed or a paid one) the snipe loses 2 to 5 % per trade
after costs. The one tier that pays sits in front of bundles we do not send;
the tier right behind them pays about what the median competitor already
bids. Being "always in right at release" would mean a shred feed, a sender in
the leaders' region and tips that the measured edge does not cover.

## 3. The block sample

149 creation slots spread over the record (quarter-hour slices, slots with an
outside buyer first), read once with `getBlock` (account details) from the
public RPC:

- 138 have outside buyers in the creation slot; a median of 3 (90th
  percentile 5).
- The first outside buyer is usually the very next transaction after the
  creation (median distance 1); 56 % of the outside buyers stand in an
  unbroken run directly behind it.
- Bids of outside same-slot buyers: median 0.0011 SOL (priority fee plus
  tips), 75th percentile 0.0062, 90th 0.029; the best bid per slot: median
  0.0033, 75th 0.028, 90th 0.060, 99th 0.50 SOL. The priority fee alone is
  small (median 0.0001 SOL); the bidding is in tips. 11 % of them tip Jito,
  38 % tip another relay (34 tip accounts found by their payments not
  following the trade size; 27 accounts that take a fixed share of the trade,
  pump.fun's fee recipients and trading-bot platform fees, are not counted as
  bids).
- Our order inside a slot (the reserve chain) equals the block's order in all
  120 slots where it could be compared.

## 4. The fast path (dry run only)

Built in `fastpath.py`: a template per new mint made from the creation event
alone (bonding curve, creator and token program are in the event; the mint's
associated accounts and the creator vault are derived on arrival, the
program-wide accounts once), the buy and the sale compiled once and only
patched at the signal (amounts, compute-unit price, blockhash); a blockhash
cache refreshed every 20 s; the compute-unit price as the 75th percentile of
recent prioritization fees of the pump.fun accounts, capped by
`PYTHIA_PUMPFUN_MAX_PRIORITY_SOL` (default 0.005 SOL, hard cap 0.01); a
dry-run sender that records what a parallel send to several RPCs (and, behind
`PYTHIA_PUMPFUN_JITO=1`, a Jito block engine) would have done. A tip is an
instruction inside our own single transaction, to a published Jito tip
account, at most 0.01 SOL, at most one, refused by `txbuild.check_own` unless
the owner's flag is on. No bundle with anyone else's transaction.

Internal latency, receipt of the raw websocket message to a signed
transaction (fake signer), on this PC:

| | p50 | p90 | p99 |
|---|---|---|---|
| a new mint (parse, decode, derive the template, patch, sign) | 0.26 ms | 0.37 ms | 0.54 ms |
| of that, deriving the template | 0.20 ms | 0.30 ms | 0.45 ms |
| a sale with the mint's ready template | 6 us | | 14 us |
| creation messages captured from the public stream (24) | 0.52 ms | | |

A real Ed25519 signature adds tens of microseconds (not measured here: no
module but the wallet tool may hold a key). The path's own time is about a
thousandth of the feed's 15 s. To get there, the program-address check now
uses the Jacobi symbol (four times faster than the power it replaced, the
same answer) and addresses are memoised.

A 60-second dry run on the public stream built 5 plain creations (6 others
were not plain SOL curves) a median 0.50 ms after receipt; those creations
were a median 30 s old when they arrived. Nothing was sent.

## 5. The feed and the gate

- The collector takes provider websocket URLs from `PYTHIA_SOLANA_WS_URLS`
  (a `{token}` in a URL is filled from `PYTHIA_SOLANA_TOKEN`; no key in any
  file of the repository; only scheme and host are ever logged) and keeps the
  public endpoint as a fallback link; `PYTHIA_SOLANA_COMMITMENT=processed`
  for speed; and a Yellowstone gRPC feed (`PYTHIA_SOLANA_GRPC_URL`,
  `PYTHIA_SOLANA_GRPC_TOKEN`, `geyser.py`, hand-written protobuf for the few
  fields needed, needs grpcio) next to the websockets. The heartbeat counts
  which feed delivered each transaction first.
- `live_exec`'s gate: a Jito block engine is allowed only with
  `PYTHIA_PUMPFUN_JITO=1`, only https and only its single-transaction
  endpoint (never bundles); further RPCs for parallel sending
  (`PYTHIA_PUMPFUN_RPC_URLS`) are checked like the main one. The executor
  itself still sends only to `PYTHIA_PUMPFUN_RPC`; the fast path is not wired
  into it.
- What a paid feed would cost and change, and that it is the owner's
  decision: `docs/PUMPFUN-LIVE.md`, section 10.

## 6. Daily

The study (`pumpfun-rt-study`, no new job) now measures the last 24 hours'
detection latency (`reports/pumpfun_rt/latency.{md,json}`, a section of the
study's report), and the daily card has one more line (English and German),
for example "Our feed saw new tokens 14.9 s after their block (median; 90th
percentile 43.7 s), 4% within a second, 3% within two slots." The tiers are a
one-off study (`python -m lab.pumpfun_rt.speed`, about 3 minutes on a day of
record; `speed blocks` reads the block sample).

## Counting

135 trials (8 tiers x 5 filters x 3 exits, plus `S0r`'s 15) in
`strategies.N_TRIALS`; the pump.fun real-time share of the pool is now 224.
