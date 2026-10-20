"""Polymarket research: public data, a calibration model, a Claude forecaster, a PAPER book.

PAPER ONLY. Nothing in this package holds a wallet, a key or a signer, and
nothing places, signs or sends an order. It reads Polymarket's public Gamma
and CLOB endpoints (no account, no key) and simulates fills against the order
book it read. Polymarket restricts trading in several countries; this is
research into whether a model can beat the market price at all.

  api.py       the HTTP client: rate limit, retries, keyset paging
  markets.py   one flat record per market (category, fees, outcome, tokens)
  store.py     the data folder, parquet files and the size budget
  collect.py   resolved markets with their price history; the daily snapshot
               of open markets with books
  panel.py     point-in-time market states from the price history
  study.py     the pre-registered study: biases, the calibrated model against
               the market price, the historical paper rule
  forecast.py  the Claude forecaster and its append-only ledger
  book.py      the paper book: edge rule, Kelly sizing, fills on the book,
               fees, settlement at resolution
  daily.py     the daily run: snapshot, settle, forecast, step the book,
               report, Telegram card and big-edge alerts
  card.py      the Telegram cards (English or German)

See results/polymarket_prereg.md (written before anything was computed) and
results/polymarket.md.
"""
