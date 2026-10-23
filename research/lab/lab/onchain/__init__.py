"""Our own Solana wallet as a venue, stage 1: paper trading on chain through Jupiter quotes. No real money.

  mints.py    the coins tradable on Solana with deep liquidity, as the SPL tokens
              their official listings name, and the Kraken/Alpaca coin each stands for
  jupiter.py  Jupiter's public quote and price API (no key): timeouts, retries, pacing
  paper.py    the paper executor: a swap filled at the quote's out amount minus
              Solana's base fee and a priority fee
  book.py     the paper book that mirrors breakout_top10_live on a 1,000 USDC
              account, and the cost report reports/onchain/latest.md

Stage 2, the real-money trader, LOCKED until the owner arms it (docs/ONCHAIN-STAGE2.md, section 7):

  swapapi.py       Jupiter's /swap/v2/build: a swap's raw instructions for our wallet
  tx.py            v0 messages with lookup tables, built and read back from the bytes
  guard.py         refuses everything but the planned swap inside our own wallet
  live_gate.py     the ack, the hard maxima, the wallet file, the simulation, the kill switch
  live_exec.py     caps, build, guard, simulate, sign, send, ledger against the chain
  live_service.py  the service pythia-onchain-live: the app's converts, the books, the status
  wallet.py        the owner's wallet tool for this wallet

Stage 1 (mints, jupiter, paper, book) never signs or sends (docs/ONCHAIN.md); in stage 2 only
live_exec.py signs, after every gate held, and nothing anywhere transfers out of the wallet.
"""
