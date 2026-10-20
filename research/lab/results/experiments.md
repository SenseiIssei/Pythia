# Experiments: rules that failed the bar, run on paper anyway

Written 2026-10-15. Code: `lab/paper/experimental.py`, `lab/paper/memes.py`,
`lab/paper/trend4h.py`, `lab/paper/pumpfun.py`.

The owner asked for more risk and more activity, on paper. The lab's bar has
not moved: a strategy needs an out-of-sample Sharpe above zero after costs,
a drawdown it can live with, a survivorship-free twin and a late fill that
still work, and a deflated Sharpe probability above 0.95 over every trial
ever counted. Nothing below clears that bar. These books run so that forward
evidence accumulates, and they say so everywhere:

- **Labelled.** Every signal carries `"experimental": true` (at the top and in
  its evidence) and `"autopilot_only": true`; the variant string starts with
  `EXPERIMENT, failed deflation`. The Autopilot page shows an "Experiment"
  badge on such a sleeve, the Research page on such a book, and every trade
  line in Telegram says "experiment" (`Memes (experiment) bought ...`, a card
  title ending in "· experiment", the coin marked "(exp)" in a rebalance
  table).
- **Never chosen by Pythia.** The engine's auto pick, a re-pick and a
  portfolio's class pick all skip experimental lab books, however good their
  numbers look. An autopilot runs one only when the owner names it as a
  sleeve.
- **Never with real money.** A live autopilot refuses an experimental sleeve,
  and the live setup does not even list one. Paper and demo (the Alpaca paper
  account) only.
- **Never on their own.** An experimental signal is autopilot-only whatever
  else it says: the engine creates the book idle and it trades only inside an
  autopilot that claims it.

## The sleeve ids

| sleeve id | what | cadence | signal valid |
|---|---|---|---|
| `lab:memes_rotation` | the best of Alpaca's six memecoins by 28-day return, BTC gate | daily, 04:30 UTC | 36 h |
| `lab:memes_tsmom` | Alpaca's six memecoins while each is up over 28 days, BTC gate, 6 slots at 40 % vol | daily, 04:30 UTC | 36 h |
| `lab:trend4h_pullback` | 4h EMA 24/96 trend with pullback limits, BTC gate, Alpaca coins | hourly run, decisions at every 4h close | 3 h |

The pump.fun books have no engine signal: they are paper only, in the lab.

## 1. Memecoin rotation (`memes_rotation`)

**Rule.** Among DOGE, SHIB, PEPE, BONK, WIF and TRUMP (the memecoins the
Alpaca paper account lists), hold the one with the highest 28-day return,
only if that return is above zero and BTC's close is above its 200-day
average; size it at 40 % annual volatility (at most the whole sleeve). The
weight function is W7's own (`experiments/memecoins.py`, `rotation(P, A, 1)`).

**Backtest (W7, results/memecoins.md, out of sample from 2024 at 35 bps,
Alpaca taker plus slippage).** Sharpe 1.15 (0.94 at 70 bps), drawdown 27 %,
CAGR 35 %, positive in 2024, 2025 and 2026. The survivorship-free twin (the 6
most liquid of 24 Binance memecoins each day, crashed ones included) 1.11;
filled a day late 1.06. Against BTC buy and hold 0.74 (drawdown 53 %).

**Why it failed.** It lost the pre-registered in-sample pick to the momentum
rule by 0.006 of Sharpe, and would have failed anyway: deflated p 0.01 over
427 trials (the bar there was a Sharpe of about 2.35). Its bootstrap 90 % band
at 35 bps runs from -0.24 to 2.27, and 52 % of its out-of-sample P&L is one
coin, PEPE. It holds one coin at a time, so its risk is a single memecoin's.

**What would change the verdict.** 90 forward days with a Sharpe above 0.5 at
Alpaca's costs, a drawdown under its backtest's 27 %, and P&L that does not
come from a single coin. Even then it would have to pass a new pre-registered
study with the trials counted, not this one re-read.

## 2. Memecoin momentum (`memes_tsmom`)

**Rule.** Each of the six held while its 28-day return is above zero and BTC
is above its 200-day average, each at 40 % vol over 6 slots (at most 1/6 of
the sleeve each), rebalanced daily (`trend(P, A, 28, True)`).

**Backtest.** W7's pre-registered pick: Sharpe 0.67 at 35 bps (0.77 at 15,
0.50 at 70), drawdown 19 %, twin 0.75, a day late 0.75. Average exposure 10 %.

**Why it failed.** Below BTC buy and hold over the same days (0.74), so it
does not earn its risk against the simplest alternative; deflated p 0.00 over
427 trials.

**What would change the verdict.** 90 forward days above BTC's Sharpe over
the same window, with a drawdown under 19 %.

## 3. 4h trend with pullback entries (`trend4h_pullback`)

**Rule.** W15's in-sample pick in its only paying family, "B EMA 24/96 · p 0.5
· W 1h · BTC gate", on the 33 coins Alpaca lists (stablecoins out). At every
4h close where the coin's 24-bar EMA is above its 96-bar EMA, BTC is above
its 200-day average and the coin is flat, a buy limit at close x (1 - 0.5 x
the 4h vol) rests for one hour; it fills only where the price trades at least
1 bp through it (a share by depth, all at 10 bps), never more than 10 % of the
hour's volume. Size min(40 % / coin vol, 1) / 10 of the book, at most 100 %
in all. Exit: at the first 4h close with the trend or the gate off, a sell
limit at the hour's close, re-placed every hour, the rest at taker cost after
24 hours. Maker fills pay 15 bps and are booked 3 bps worse.

**Backtest (W15, results/fast_maker.md, 1h bars, out of sample from 2024).**
Sharpe 0.71 with resting maker fills, 0.51 with every order filled at the
close at taker cost (35 bps a side); drawdown 44 %; 0.62 round trips a day,
18 % of entry orders fill, 243 bps net per round trip, holds about 10 days.
Twin 0.40, an hour late 0.52; per year 1.70, -0.91, 1.12. The registered
5-minute run on the server (results/fast_maker_5m.md) gives the same pick the
same numbers (0.71 maker, 0.51 taker, twin 0.40, a bar late 0.56; per year
1.71, -0.93, 1.11), and the fill model matched real aggTrades on 98 % of 1,314
orders. The engine's evidence reads the 5-minute run where it exists.

**Why it failed.** Deflated p 0.00 over 841 trials (bar 2.72); 2025 was
negative; its bootstrap band runs from -0.70 to 1.92; BTC made 0.74 over the
same days. It is the only family of the fast study that paid at all, and it
pays because it holds for days, not hours.

**How the engine runs it.** The paper book (`lab.paper.trend4h`, hourly)
simulates the study's fills on live Binance 1h and 4h klines. Its signal is
the book's holdings; a new signal is written only when the holdings change
(an entry fill or an exit decision), so the engine trades once per change and
does not chase drift every hour. The engine buys after the paper book's
limit filled, at its own maker price on the Alpaca route (which already rests
maker limits), so its fills will differ from the paper book's. The forward
report shows both.

**What would change the verdict.** 90 forward days with an entry fill rate
near the backtest's 18 %, net above 100 bps per round trip and a Sharpe above
0.5; and the engine's own maker fills not far from the paper book's.

## 4. pump.fun paper watcher (`pumpfun_migration`, `pumpfun_filtered`, `pumpfun_filtered_quick`)

**What it is.** A paper-only watcher of Solana memecoins launched on
pump.fun. It reads public data only and holds no wallet, no key and no
transaction code; a test checks the module for any of it.

**Sources and terms.** pump.fun's own frontend API is not used: its terms of
use (sections 6.1 and 21(h), dated 2026-10-08) forbid bots and other automatic
access unless pump.fun expressly permits it. The watcher reads GeckoTerminal's
free public API (new Solana pools; holders, top-10 share, mint and freeze
authority, honeypot flag per token; documented at 30 calls a minute, but it
answered 429 after a short burst when tested, so the watcher makes at most 8
calls a run, 6.5 s apart) and DexScreener's public API (pair prices and
liquidity, documented at 300 calls a minute on pair endpoints; at most 20 a
run). A 429 stops calls to that host for the run.

**Candidates.** Every new pool on GeckoTerminal's "pump-fun" dex is a new
token on the bonding curve and is counted. A new pool on "pumpswap" whose
mint ends in "pump" is a graduation (the bonding curve completed and the token
migrated to PumpSwap): the only moment a rule may buy. The watcher reads the
newest pools every 5 minutes, about 100 of them, so between runs some are
missed; the sample is taken by time, not by outcome, and the report counts
the runs that did not reach back to the run before.

**Pre-registered rules** (fixed before the first paper position; a change is
a new rule with a new name):

| rule | entry | exit |
|---|---|---|
| `migration` | every graduation with $10,000+ of pool liquidity | 24 h, or a 30 % trailing stop from the best mark |
| `filtered` | $20,000+ liquidity, 300+ holders, top 10 under 30 %, mint and freeze authority renounced, not flagged a honeypot | 72 h, or a 40 % trailing stop |
| `filtered_quick` | as filtered | +100 %, 6 h, or a 25 % trailing stop |

$100 a token, at most 40 open per rule, each rule a paper book from $10,000.

**Fills.** Entry at the pool price of the run that sees the graduation (up to
5 minutes late, never the migration price), through constant-product AMM
arithmetic on the pool's quote reserve: the pool fee (1.25 % a side, the top
of PumpSwap's low market cap tier, so not flattering; pump.fun's 1 % applies
only on the bonding curve, which these rules never trade) comes off first,
then the trade moves the price along x * y = k. A Solana base and priority fee
of 0.002 SOL per transaction is charged on top. Exits sell through the same
arithmetic at the mark that triggers them; between 5-minute marks the price is
not seen, so a stop fills where the next mark is.

**Rugs.** A pool whose liquidity falls under $500, or a token without any
pool in three runs spanning at least an hour, is closed at zero: a total loss.
A price still quoted on an empty pool is not a value.

**Tracking.** Every run marks the open positions; once an hour each one is
written to `paper/pumpfun/marks.csv`; every paper fill is in
`paper/pumpfun/ledger.csv`; each rule journals a daily row in
`paper/pumpfun_<rule>/journal.csv`, so the forward report lists them.
`python -m lab.paper.pumpfun --report` (daily) writes `reports/pumpfun/latest.json`
with the lab feed header (title, updated_ms, status, headline, items) and posts
a card; a closed position at +100 % or better is posted at once, closes at
-80 % or worse (rugs included) together at most once an hour, category
"trending".

**The honest expectation.** There is no backtest: no free source keeps the
pool-level history of every pump.fun token, dead ones included, and a
backtest on the tokens that are still findable would be survivorship in its
purest form. What is known: well under 2 % of pump.fun tokens ever complete
their bonding curve, and most of those that do fall far below their
graduation price within days. Buying at graduation, after the run-up that got
the token there, with 1.25 % in and 1.25 % out plus slippage on a pool of tens
of thousands of dollars, the expected result is a loss, with a long tail of
rare large winners that a $100 stake per token is sized for. Most of these
paper positions should end at or near zero. The books measure how fast and
how often, and whether the filters change that; a positive number after a
month would most likely be the tail, not an edge.

**What would change the verdict.** Nothing short of a pre-registered study on
a survivorship-free history of graduations (every one, from an on-chain
source), out of sample, deflated over every trial, with these paper books as
its forward test. Until then: paper only, and never a wallet.

**Forward result and what came next.** After five days buying every
graduation had lost badly (1,209 closed, median -96 %, 61 rugs, hit rate
11 %) and the filtered books had barely traded. A 5-minute poller cannot see
the first seconds, where most tokens are dumped, so the question moved to the
real-time lab (`lab.pumpfun_rt`, `results/pumpfun_realtime.md`): every
creation and curve trade recorded from the chain as it happens, fills with
latency, 22 pre-registered rules and a model, paper only.

## Where the numbers come from

The engine reads each experiment's evidence from the study's markdown
(`experimental.evidence()`): Sharpe at Alpaca's costs, the stress cost, the
drawdown, deflated p and the number of trials, the twin, the reason it failed
and what would change it. The forward report labels the books "EXPERIMENT" and
marks them `experimental` in `reports/forward/evidence.json`; their range is
the approximate one from the study's growth and volatility.
