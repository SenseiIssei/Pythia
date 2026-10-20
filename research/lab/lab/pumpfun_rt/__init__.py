"""Real-time pump.fun lab, PAPER unless the owner unlocks the live executor.

A long-running collector records every pump.fun token creation, every bonding
curve trade, every curve completion and migration, and the first day of
PumpSwap trading of each token that migrated while it watched, from a public
Solana RPC websocket (logsSubscribe on the two public programs). Every paper
buy and sell is arithmetic on the recorded curve, written to a paper ledger.
Only live_exec.py could sign and send, inside the live service the owner starts
by hand (live_service.py), and it refuses unless every one of its gates holds
(see its docstring, docs/PUMPFUN-LIVE.md and research/ops/README.md). Only the
owner-run wallet tool (wallet.py) makes a key; no other module holds a wallet,
reads a key, signs or sends anything (a test checks), and nothing anywhere
transfers or withdraws money.

    python -m lab.pumpfun_rt.collector     the service (docker, --restart unless-stopped)
    python -m lab.pumpfun_rt.health        exits 1 when the collector wrote nothing for 10 minutes
    python -m lab.pumpfun_rt.categorize    daily: yesterday's token names into categories (Claude Haiku)
    python -m lab.pumpfun_rt.study         daily: rules and pipeline strategies, readiness, report
    python -m lab.pumpfun_rt.retrain       daily after the study: models, the card
    python -m lab.pumpfun_rt.wallet new    the OWNER makes the live wallet, interactively (never a job)
    python -m lab.pumpfun_rt.live_exec check      why the live executor is shut
    python -m lab.pumpfun_rt.live_exec simulate   the test gate's dry run on mainnet (nothing sent)
    python -m lab.pumpfun_rt.live_service  the live book (started by hand only)

Modules:

  events     decoding the programs' event logs (Anchor events, Borsh)
  store      compact parquet part files by day, with a size budget
  curve      bonding curve and pool arithmetic, the latency and fee model
  tokens     per-token state and the features a decision may use
  strategies the pre-registered rules (results/pumpfun_realtime_plan.md)
  pipeline   the trading pipeline shared by paper and live: strategies, sizing, risk, exits
  wallets    wallet reputation (smart money, flippers), point in time
  categorize name categories through the engine's metered Claude endpoint
  sim        replaying recorded days through the execution model
  model      labels, feature sets, purged time-ordered splits, calibration, baselines
  live       the shadow paper books that run inside the collector
  study      the daily job; retrain the daily models; card the Telegram cards
  txbuild    plain buy and sell transactions (bytes only)
  wallet     the owner's wallet tool (the only code that makes a key)
  live_exec  the live executor, locked unless the owner unlocks it (full or test mode)
  live_service the live book's own long-running process
  measure    measured latency, slippage and fees of live fills against the paper model

See results/pumpfun_realtime.md.
"""

NAME = "pumpfun_rt"
