"""The model zoo: every model the lab keeps, with one way to train, judge, publish and watch it.

  core.py      the spec every model has, walk-forward evaluation against its
               baseline, cards, drift and live shadow scoring
  zoo.py       the list: M1, M2 and M7 as they already exist, the zoo's
               own models M8, M8q, M8u, M10, M11 and M12, and X16's records
               M13, M14 and M15 (failed gates, never retrained)
  m8_direction.py, m8_quantiles.py, m8_upper.py, m10_vol_regime.py,
  m11_slippage.py, m12_cross_asset.py
               one file per zoo model: data, features, fit, baseline
  train.py     the cron entry point: python -m lab.models.train --due

M1 (results/modern_models_m1.md), tools the zoo's models and the studies can use, paper only:

  factory.py   the model factory: the learners (base rate, logistic, LightGBM, histogram boosting, CatBoost,
               TabPFN v2) behind one interface, the zoo's gate, a walk-forward, the loan to the pump.fun zoo; since G2
               also specs made by themselves, screened, held back over all trials and rotated as zoo shadows
  fm.py        Chronos-Bolt and TimesFM 2.5 zero shot, pinned weights, a forecast cache and a time budget
  conformal.py rolling split conformal intervals and a sizing on their width
  metalabel.py the trades of a book's weights, their after-cost labels and entry features, a paper filter
"""
