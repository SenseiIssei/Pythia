"""US equities for X16 (results/equities_training_prereg.md).

  panel.py   the point-in-time S&P 500 with opens, highs, lows and volume,
             the SPDR sector ETFs and SPY, fill prices for next-open fills
  edgar.py   SEC EDGAR: ticker to CIK, filing dates, earnings events
  books.py   the signals, an event-book and rebalanced-book simulator with
             next-open fills, the exit rules, capture and the gates
  features.py the model rows of M13 (event candidates) and M15 (held days)
"""
