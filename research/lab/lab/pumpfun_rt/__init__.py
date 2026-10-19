"""Real-time pump.fun lab, PAPER ONLY.

A long-running collector records every pump.fun token creation, every bonding
curve trade, every curve completion and migration, and the first day of
PumpSwap trading of each token that migrated while it watched, from a public
Solana RPC websocket (logsSubscribe on the two public programs). Nothing in
this package holds a wallet, reads a key, signs or sends anything: every buy
and sell is arithmetic on the recorded curve, written to a paper ledger.

    python -m lab.pumpfun_rt.collector     the service (docker, --restart unless-stopped)
    python -m lab.pumpfun_rt.health        exits 1 when the collector wrote nothing for 10 minutes
    python -m lab.pumpfun_rt.study         daily: strategies, model, report, card

Modules:

  events     decoding the programs' event logs (Anchor events, Borsh)
  store      compact parquet part files by day, with a size budget
  curve      bonding curve and pool arithmetic, the latency and fee model
  tokens     per-token state and the features a decision may use
  strategies the pre-registered rules (results/pumpfun_realtime_plan.md)
  sim        replaying recorded days through the execution model
  model      labels, purged time-ordered splits, calibration, baselines
  live       the shadow paper book that runs inside the collector
  study      the daily job

See results/pumpfun_realtime.md.
"""

NAME = "pumpfun_rt"
