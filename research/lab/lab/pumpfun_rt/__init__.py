"""Real-time pump.fun lab, PAPER unless the owner unlocks the live executor.

A long-running collector records every pump.fun token creation, every bonding
curve trade, every curve completion and migration, and the first day of
PumpSwap trading of each token that migrated while it watched, from a public
Solana RPC websocket (logsSubscribe on the two public programs). Every paper
buy and sell is arithmetic on the recorded curve, written to a paper ledger.
Only live_exec.py could sign and send, and it refuses unless every one of its
gates holds (see its docstring and research/ops/README.md); no other module
holds a wallet, reads a key, signs or sends anything (a test checks).

    python -m lab.pumpfun_rt.collector     the service (docker, --restart unless-stopped)
    python -m lab.pumpfun_rt.health        exits 1 when the collector wrote nothing for 10 minutes
    python -m lab.pumpfun_rt.categorize    daily: yesterday's token names into categories (Claude Haiku)
    python -m lab.pumpfun_rt.study         daily: rules and pipeline strategies, readiness, report
    python -m lab.pumpfun_rt.retrain       daily after the study: models, the card
    python -m lab.pumpfun_rt.live_exec check   why the live executor is shut

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
  live_exec  the LOCKED live executor

See results/pumpfun_realtime.md.
"""

NAME = "pumpfun_rt"
