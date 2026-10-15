"""Every model the lab keeps, in one list.

M1 and M2 existed before the zoo: the nightly learning loop (lab.ops.learn)
retrains them as challengers and the engine scores them live, so the zoo only
reports on them. M7 failed as a gate and is kept here as a record. M8, M8q,
M10, M11 and M12 are the zoo's own: lab.models.train retrains them when due,
judges every challenger against the champion, scores the champion in shadow
every day and watches its inputs for drift.
"""

from __future__ import annotations

from importlib import import_module

import numpy as np

from ..ops import guard, registry
from . import core
from .core import Spec

M1 = Spec(
    code="M1", name="vol_1h", title="Next-hour volatility",
    target="log realised variance of the next hour (sum of squared 1-minute log returns)",
    features=["see lab.experiments.vol FEATURES (24 inputs)"], horizon="next hour", horizon_days=0,
    universe="the 20 recorded coins", metric="qlike", baseline="HAR on 1, 24 and 168-hour RV",
    every_days=7, weekday=6, managed_by="learn", shadow="engine",
    status_note="Beats HAR in 24 of 24 quarters (11.8 % lower QLIKE). Scored live by the engine (pythia-ml).",
    use_rule="Shadow only. vol_managed showed it sizes worse than the 30-day mean at Alpaca costs.",
    results="vol_managed.md",
)
M2 = Spec(
    code="M2", name="picks_7d", title="Weekly coin ranking (LambdaRank)",
    target="rank of each coin's next 7-day return", features=["see lab.experiments.picks"],
    horizon="next 7 days", horizon_days=7, universe="the liquid USDT coins and perps", metric="rank_ic",
    higher_better=True, baseline="no skill (rank-IC 0)", every_days=28, managed_by="learn", shadow="engine",
    status_note="Walk-forward rank-IC positive with t above 2. Ranked live by the engine every week (shadow).",
    used_by=["picks_ls (paper)", "picks_ls_v2 (paper)"],
    use_rule="The two market-neutral paper books retrain their own copy weekly; no autopilot uses it.",
    results="xs_daily.md",
)
M7 = Spec(
    code="M7", name="regime_hmm", title="Regime HMM (gate)", target="bull or bear state of the coin market",
    features=["r7", "vol14", "breadth", "volume", "funding"], horizon="next day", horizon_days=1,
    universe="the survivorship-free daily panel", metric="sharpe", higher_better=True,
    baseline="the BTC 200-day rule", every_days=0, managed_by="retired", shadow="none",
    status_note="Failed as a gate: no difference to the 200-day rule survives deflation; it hurts breakout_top10.",
    use_rule="Retired. The 200-day rule stays.", results="regime_hmm.md",
)

ZOO_MODULES = ("m8_direction", "m8_quantiles", "m10_vol_regime", "m11_slippage", "m12_cross_asset")


def module(name: str):
    return import_module(f"{__package__}.{name}")


def zoo_modules() -> list:
    return [module(n) for n in ZOO_MODULES]


def all_specs() -> list[Spec]:
    return [M1, M2, M7] + [m.SPEC for m in zoo_modules()]


def by_key(key: str):
    """A zoo module by name or code (m8_direction, m8, M8)."""
    k = key.strip().lower()
    for m in zoo_modules():
        if k in (m.SPEC.name, m.SPEC.code.lower()):
            return m
    raise KeyError(key)


def register_all() -> None:
    """Every zoo model into the champion/challenger registry, with its own gate,
    score (mean loss, lower is better) and champion predictor."""
    for mod in zoo_modules():
        s = mod.SPEC
        assert s.name in guard.ZOO_MODELS, f"{s.name} is not in guard.ZOO_MODELS"
        cfg = {"metric": s.metric, "higher_better": s.higher_better, "margin": s.margin, "relative": s.relative,
               "embargo_us": core.embargo_h(s) * 3_600_000_000, "min_rows": s.min_rows, "min_days": s.min_days}

        def gate_fn(folder, card):
            g = card.get("gate") or {}
            return bool(g.get("passed")), g.get("why") or "no gate recorded"

        def score_fn(frame, pred, mod=mod):
            y = frame["target"].to_numpy().astype(float)
            return float(np.nanmean(mod.loss(y, np.asarray(pred, float))))

        def predictor_fn(folder, mod=mod):
            fitted = mod.restore(folder)
            return lambda frame: mod.predict(fitted, frame)

        registry.register(s.name, cfg, gate_fn, score_fn, predictor_fn)
