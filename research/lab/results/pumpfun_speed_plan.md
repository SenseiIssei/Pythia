# pump.fun speed tiers (Y3): pre-registration (2026-10-21)

Written and committed before any tier below was computed on recorded data.
Code: `lab/pumpfun_rt/latency.py` (our detection latency), `lab/pumpfun_rt/speed.py`
(the tiers), `lab/pumpfun_rt/fastpath.py` (the fast path, dry run only). Paper
only: nothing here holds a wallet, reads a key or sends a transaction. A
change to anything below is a new trial with a new name.

The owner asked for the snipes to be "always in right at release". The
question here is whether that pays after costs, and at which speed.

## What was looked at before this plan

Disclosed, because it shaped the plan: the delivery delay of the current feed
(receive time of a token's creation against the chain's own block time) was
read on a read-only copy of the server's record (2026-10-20 16:40 to 22:11 UTC,
11,258 creations), and a two-minute probe of the public endpoint compared
its log notifications with its own slot notifications. Both say the public
feed is many seconds late (median about 15 s on the record). No tier, filter
or exit result was computed before this plan.

## 1. Detection latency (descriptive, no trial)

For every creation in the record:

- **chain time of a slot**: the program's block timestamp (`bts`, whole
  seconds) fitted against the slot number by least squares in windows of 15
  minutes (`bts * 1000 + 500` on the slot; the rounding is uniform, so the
  fit is unbiased); the slot length is that fit's slope.
- **detection latency**: our receive time of the creation minus the chain
  time of its slot, in ms and in slots (divided by the slot length).
- **clock-free checks**: how many newer slots we had already received any
  event of when the creation arrived (the "seen tip"), and the delay behind
  the first event we received of the same slot.
- Buckets: within the creation slot (under one slot), +1, +2, 3 to 4 slots
  (about a second), 5 to 9, 10 to 49, 50 or more. Per UTC hour: count,
  10th, 50th and 90th percentile.

The live probe (`python -m lab.pumpfun_rt.latency probe`) reports the same for
any endpoint against that endpoint's own slot notifications, at "confirmed"
and "processed" commitment.

## 2. Speed tiers

**Entries.** Every plain SOL curve token (as the lab defines it: no mayhem, no
other quote mint, no erratic reserves) is a snipe candidate at its creation.
Stake 0.1 SOL. The buy asks for the tokens the stake buys at the state after
the creation transaction (the dev buy included: that is what a fast path
sees) with a cost limit of stake x 1.30; it fails above the limit or when the
curve completed first, losing the transaction fee.

**Order inside a slot.** The trades of a token in one slot are put in chain
order by their reserves (each trade's virtual SOL reserve after the trade
minus its own SOL amount is the reserve before it; the chain is followed from
the state before the slot), the collector's receive order where the chain is
ambiguous. A block sample (section 4) checks this order against the block's
own transaction order.

**Tiers** (where our buy lands; "back" means after every trade of the token in
that slot, i.e. our priority fee or tip does not beat any same-slot buyer):

| tier | lands | fill state |
|---|---|---|
| `S0f` | the creation slot, first after the creation transaction (our fee or tip beats every same-slot buyer) | after the creation transaction |
| `S0b` | the creation slot, back | after the creation slot |
| `S1` | creation slot + 1, back | after slot + 1 |
| `S2` | creation slot + 2, back | after slot + 2 |
| `T1` | 1 s after the creation slot's chain time, back of that slot | after the last slot that started within 1 s |
| `T2` | 2 s, the same | within 2 s |
| `NOW` | the token's own measured detection latency (section 1) plus two slots to send, back | after that slot |
| `LM` | the paper model's latency (lognormal, median 1 s, 0.4 to 3 s, `curve.Costs`), back | after that slot |

**Sales** land as fast as the tier's buys after the exit's signal: `S0f`,
`S0b` and `S1` one slot after the signal's slot (back), `S2` two, `T1` and
`T2` 1 s and 2 s, `NOW` a draw from the record's own delivery delays of curve
trades plus two slots, `LM` the paper model's draw. A sale takes what the
curve (after completion the pool) pays then, fee off; the curve is not moved
by our own trade (impact paid twice, against us).

**Costs.** The token's own fee a side (1.25 % at the time of writing), the
base fee and the lab's 0.001 SOL priority fee per transaction. No tip is
charged inside the tiers; the tip is what the break-even answers.

**Filters** (known at creation only):

| filter | entry |
|---|---|
| `all` | every candidate |
| `dev` | the dev buy is 0.5 to 5 SOL |
| `cmig` | the creator had an earlier token complete its curve while we watched |
| `clean` | the creator dumped none of its earlier tokens and made fewer than 3 before |
| `wallet` | the dev buy is at least 0.5 SOL and the creator's wallet is not a flipper in the wallet book (point in time) |

**Exits:**

| exit | rule |
|---|---|
| `lad` | the pipeline's snipe exits: ladder +30 % (half) / +80 % (rest), stop -30 %, trail 15 % after +20 %, dev sell, liquidity pull, time stop 30 s |
| `hz` | the X14 hazard exit HZ(k*) with dev sell and pull, time stop 30 min (E0's price exits where the models are missing); its models are fit on the in-sample half only |
| `t15` | a time stop only: everything sold 15 s after the buy landed |

**Trials.** 8 tiers x 5 filters x 3 exits = **120 trials**, added to
`strategies.N_TRIALS`. No position limits (every candidate is entered), so
the tiers compare like with like.

**Split.** In sample to the record's midpoint, out of sample after (as the
daily study). The hazard models see only in-sample rows. Every number is
reported out of sample, the full record next to it.

## 3. What is reported per tier, filter and exit

Trades, failed buys, mean and median return per trade (P&L over the stake,
every cost in, failed buys as their fee), hit rate (P&L above zero), rugs (a
position that lost half its cost or more), P&L in SOL, the hour-block
bootstrap 90 % band of the mean (the study's), and:

- **break-even tip**: the mean P&L per trade in SOL before any tip, the most
  an extra tip per round trip could cost before the tier loses on average
  ("none" when it already loses);
- **value of the front**: per token, `S0f` minus `S0b` (what out-bidding the
  same-slot buyers is worth), mean and median, with the observed bids of
  those buyers (section 4) next to it.

**Verdict rule.** Speed pays at a tier when its out-of-sample mean P&L per
trade, every cost in, is above zero with the band's lower end above zero, at
300 or more trades over 14 or more days (the lab's bar). Before that, the
report says "too early" and states only whether the means rise with speed and
whether any tier is above zero. Being first is worth something when `S0f`
minus `S0b` is positive and above the observed winning bid.

## 4. Block sample (in-slot order and the bids of same-slot buyers)

For up to 150 creation slots of plain tokens (every fourth hour-slice of the
record, those with at least one buyer other than the dev in the creation slot
first), the block is read once from the public RPC (`getBlock`, account
details, read only, about 3 MB a block, one request a second). For each
transaction that traded the token in that block: its index (the block's
order), its signer, its priority fee (the fee above 5,000 lamports per
signature) and tips (SOL paid to Jito's published tip accounts, and to any
other third-party account that receives small payments from several unrelated
signers in the sample, counted separately as "other relay tips"). Reported:
the share of slots where the reserve chain order equals the block order, the
creation transaction's index, the number of same-slot buyers ahead of a
latecomer, and the distribution of the highest same-slot bid (priority fee
plus tip) of a sniper.

## 5. The fast path (engineering, no trial)

Pre-built transaction templates per new mint (every account derived from the
creation event, nothing read over RPC at the signal), a recent-blockhash cache
refreshed every 20 s, a compute-unit price from recent prioritization fees, an
optional parallel send to several RPC endpoints, and an optional Jito path for
our own single buy or sale with a tip behind `PYTHIA_PUMPFUN_JITO=1` (no
bundle with anyone else's transaction, no sandwich, no front-running of other
users). Measured: the internal latency from the event's receipt (the raw
websocket message) to a signed transaction (a fake signer), p50 and p99 over
creation messages captured from the public stream and 10,000 synthetic ones.
Nothing is sent.
