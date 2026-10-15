"""The model zoo: every model the lab keeps, with one way to train, judge, publish and watch it.

  core.py      the spec every model has, walk-forward evaluation against its
               baseline, cards, drift and live shadow scoring
  zoo.py       the list: M1, M2 and M7 as they already exist, and the zoo's
               own models M8, M10, M11 and M12
  m8_direction.py, m10_vol_regime.py, m11_slippage.py, m12_cross_asset.py
               one file per zoo model: data, features, fit, baseline
  train.py     the cron entry point: python -m lab.models.train --due
"""
