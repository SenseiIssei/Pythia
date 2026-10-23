"""Our own Solana wallet as a venue, stage 1: paper trading on chain through Jupiter quotes. No real money.

  mints.py    the coins tradable on Solana with deep liquidity, as the SPL tokens
              their official listings name, and the Kraken/Alpaca coin each stands for
  jupiter.py  Jupiter's public quote and price API (no key): timeouts, retries, pacing
  paper.py    the paper executor: a swap filled at the quote's out amount minus
              Solana's base fee and a priority fee
  book.py     the paper book that mirrors breakout_top10_live on a 1,000 USDC
              account, and the cost report reports/onchain/latest.md

Nothing in this package signs, sends or holds a key (docs/ONCHAIN.md).
"""
