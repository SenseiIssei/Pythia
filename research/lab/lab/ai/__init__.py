"""Rare, metered calls to the Claude API, and the scoring of what they predict.

The lab never calls the API itself. Every call goes through the engine's
POST /api/ai/complete, which holds the key and the hard budget (lifetime,
monthly and daily caps, a persisted ledger of every call, pythia-core
ai_budget.rs), so there is one gate and one ledger for every paid call in
Pythia. The lab proves it may ask by a hash of the same key
(lab.ai.engine.token), never the key itself.

  python -m lab.ai.brief     the daily market brief (Haiku), shadow predictions, scores
  python -m lab.ai.weekly    the weekly review (Sonnet): three proposed experiments,
                             written to reports/ai/weekly.md, never run by anything
  python -m lab.ai.score     score the brief's predictions again, no call

Shadow only: nothing here sizes, places or vetoes an order.
"""
