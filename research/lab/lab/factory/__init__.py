"""The strategy factory: the lab inventing and testing its own long-only daily strategies.

A typed grammar (grammar.py) composes strategies from the lab's building
blocks; a search (search.py) evaluates a fixed budget of new ones per run on
the in-sample window only; every one is a trial in a global ledger
(ledger.py) that only grows, so the deflation bar rises with every run; the
best few face the held-back window (evaluate.py), survivors run 30 days as
forward shadow books (shadow.py), and only a shadow that clears the hand
studies' bar becomes a paper book. Never live. Entry point: run.py.
"""
