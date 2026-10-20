"""The model zoo on synthetic data: specs, walk-forward gates, champion and challenger, shadow, drift, alerts.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab import report
from lab.models import core, daily, train, zoo
from lab.models import m8_direction as m8
from lab.models import m8_quantiles as m8q
from lab.models import m10_vol_regime as m10
from lab.models import m11_slippage as m11
from lab.models import m12_cross_asset as m12
from lab.ops import fills, guard, registry

NOW = int(datetime(2026, 10, 18, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)  # a Sunday
DAY_MS = 86_400_000


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for mod in (fills, guard, registry, train):
        monkeypatch.setattr(mod, "ROOT", data)
    monkeypatch.setattr(report, "REPORTS", data / "reports")
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("PYTHIA_TELEGRAM_BOT_TOKEN", raising=False)
    guard.WRITTEN.clear()
    return data


@pytest.fixture(scope="module")
def coins():
    return daily.enrich(daily.synthetic_daily(1300))


def no_data():
    raise core.DataUnavailable("not in this test")


# ---------------------------------------------------------------- specs and guardrails

def test_every_zoo_model_has_a_complete_spec_and_a_guarded_folder():
    names = set()
    for s in zoo.all_specs():
        assert s.code and s.name and s.target and s.horizon and s.universe and s.metric and s.baseline
        assert s.use_rule, f"{s.code} must say who may use it"
        assert s.name not in names
        names.add(s.name)
    for mod in zoo.zoo_modules():
        assert mod.SPEC.name in guard.ZOO_MODELS
        assert mod.SPEC.managed_by == "zoo" and mod.SPEC.every_days > 0
        for fn in ("load", "fit", "predict", "baseline", "loss", "save", "restore"):
            assert callable(getattr(mod, fn)), f"{mod.SPEC.code} lacks {fn}"
    assert zoo.by_key("m8").SPEC.code == "M8" and zoo.by_key("M12").SPEC.name == "m12_cross_asset"


def test_the_zoo_cannot_write_outside_its_folders(root):
    with pytest.raises(guard.GuardError):
        guard.check_write(root / "models" / "some_other_model" / "x.json")
    with pytest.raises(guard.GuardError):
        guard.check_write(root / "paper" / "breakout_top10" / "state.json")
    guard.check_write(root / "models" / "zoo" / "state.json")
    guard.check_write(root / "models" / "m8_direction" / "v" / "card.json")


# ---------------------------------------------------------------- drift, same rules as pythia-ml

def test_drift_check_matches_the_engine():
    bins = {"edges": [i / 10 for i in range(1, 10)], "expected": [0.1] * 10, "lo": 0.005, "hi": 0.995}
    same = core.drift_check(bins, (np.arange(1000) + 0.5) / 1000)
    assert same["level"] == "stable" and same["psi"] < 0.01
    assert core.drift_check(bins, 0.9 + np.arange(1000) / 2000)["level"] == "drift"
    assert core.drift_check(bins, 0.6 + np.arange(1000) / 5000)["level"] == "shift"
    assert core.drift_check(bins, np.array([0.1, 0.2])) is None
    ties = {"edges": [-0.5, 0.0], "expected": [0.2, 0.6, 0.2], "lo": -1.0, "hi": 1.0}
    v = np.array([-0.7] * 20 + [0.0] * 60 + [0.3] * 20)
    assert core.drift_check(ties, v)["level"] == "stable"


# ---------------------------------------------------------------- the models, honestly evaluated

def test_m8_on_noise_fails_its_gate_and_reports_calibration(coins):
    ev = core.evaluate(m8, m8.panel_from(coins))
    assert ev["rows_oos"] > 1000 and len(ev["folds"]) >= 3
    assert not ev["gate"]["passed"], "a direction model on a random walk must not pass"
    x = ev["extra"]
    assert 0.3 < x["auc"] < 0.7 and x["calibration"]
    p = ev["holdout"]["challenger"].to_numpy()
    assert np.all((p > 0) & (p < 1))
    # Calibrated: the average forecast sits near the share of up days.
    assert abs(p.mean() - x["up_share"]) < 0.05
    assert x["today"] and all(0 < t["p_up"] < 1 for t in x["today"])


def test_m8q_forecasts_three_ordered_quantiles_and_scores_each(coins):
    panel = m8q.panel_from(coins)
    ev = core.evaluate(m8q, panel)
    assert ev["rows_oos"] > 1000 and ev["model_score"] > 0 and ev["baseline_score"] > 0
    q = core.as_array(ev["holdout"]["challenger"])
    assert q.shape[1] == 3 and np.all(q[:, 0] <= q[:, 1]) and np.all(q[:, 1] <= q[:, 2])
    x = ev["extra"]
    assert [r["quantile"] for r in x["per_quantile"]] == ["q10", "q50", "q90"]
    # The 10 % quantile is undershot about one day in ten, out of sample.
    assert 0.04 < x["per_quantile"][0]["coverage"] < 0.2 and 0.8 < x["per_quantile"][2]["coverage"] < 0.96
    assert x["today"] and all(t["q10"] <= t["q50"] <= t["q90"] for t in x["today"])
    # The loss is the mean pinball over the three quantiles, row by row.
    y = np.array([0.0, 0.1])
    qq = np.array([[-0.1, 0.0, 0.1], [-0.1, 0.0, 0.1]])
    np.testing.assert_allclose(m8q.loss(y, qq), [(0.01 + 0 + 0.01) / 3, (0.02 + 0.05 + 0) / 3])


def test_m10_beats_har_but_the_regime_part_must_earn_its_place(coins):
    ev = core.evaluate(m10, m10.panel_from(coins))
    assert ev["model_score"] < ev["baseline_score"]
    assert "regime inputs" in ev["gate"]["why"] or not ev["gate"]["passed"]
    q = ev["extra"]["qlike_same_rows"]
    assert set(q) == {"model", "har", "rw30", "no_regime"} and all(np.isfinite(v) for v in q.values())


def test_m11_waits_for_fills_then_beats_a_flat_cost_model():
    with pytest.raises(core.DataUnavailable, match="needs 30"):
        m11.load(ledger={o["id"]: o for o in m11.synthetic_orders(20)}, base=None)
    p = m11.load(ledger={o["id"]: o for o in m11.synthetic_orders(400)}, base=None)
    ev = core.evaluate(m11, p)
    assert ev["gate"]["passed"], ev["gate"]
    assert ev["model_score"] < 0.6 * ev["baseline_score"]
    assert {r["symbol"] for r in ev["extra"]["by_symbol"]} == {"BTC/USD", "ETH/USD"}


def test_m11_ignores_limit_orders_and_unfinished_ones():
    o = m11.synthetic_orders(3)
    o[0]["type"] = "limit"
    o[1]["status"] = "cancelled"
    assert m11.panel_from(o, None).height == 1


def test_m12_builds_a_leak_free_target_and_names_the_regime():
    btc, spy = m12.synthetic(900)
    p = m12.panel_from(btc, spy)
    # The target of row t is the correlation of rows t+1..t+20: the last 20 rows have none.
    assert p.tail(20)["target"].null_count() == 20 and p.head(-20)["target"].null_count() == 0
    rb, rs = p["rb"].to_numpy(), p["rs"].to_numpy()
    t = 300
    want = np.arctanh(np.clip(np.corrcoef(rb[t + 1:t + 21], rs[t + 1:t + 21])[0, 1], -0.99, 0.99))
    assert abs(p["target"][t] - want) < 1e-9
    ev = core.evaluate(m12, m12.panel_from(*m12.synthetic()))
    today = ev["extra"]["today"]
    assert ev["rows_oos"] > 500 and today["regime"] in ("coupled", "mixed", "decoupled")
    # Only a model that beat its baseline names the regime; otherwise the last 60 days do.
    assert today["regime_from"] == ("model" if ev["gate"]["passed"] else "baseline")
    shown = today["forecast_corr"] if ev["gate"]["passed"] else today["corr60"]
    assert today["regime"] == m12.regime(shown)
    # Yahoo includes the day in progress; it is dropped.
    d = np.array(["2026-10-13", "2026-10-14", "2026-10-15"], dtype="datetime64[D]")
    kept = m12.complete_days((d, np.array([1.0, 2.0, 3.0])), today=np.datetime64("2026-10-15"))
    assert list(kept[1]) == [1.0, 2.0]
    with pytest.raises(core.DataUnavailable):
        m12.panel_from((btc[0][:100], btc[1][:100]), (spy[0][:100], spy[1][:100]))


def test_shadow_scores_a_forecast_of_several_numbers_once_the_outcome_is_known():
    rows = [{"ts_us": 1, "symbol": "BTC", "pred": [-0.02, 0.0, 0.02], "baseline": [-0.05, 0.0, 0.05]},
            {"ts_us": 1, "symbol": "ETH", "pred": [-0.02, 0.0, 0.02], "baseline": [-0.05, 0.0, 0.05]},
            {"ts_us": 2, "symbol": "BTC", "pred": [-0.02, 0.0, 0.02], "baseline": [-0.05, 0.0, 0.05]}]
    for r in rows:
        r.update(version="v", recorded_ms=0)
    panel = pl.DataFrame({"ts_us": [1, 1, 2], "symbol": ["BTC", "ETH", "BTC"], "target": [0.01, -0.01, None]})
    s = core.shadow_score(m8q, rows, panel)
    assert s["rows"] == 2 and s["open"] == 1
    # A narrow band that holds the outcome beats a wide one.
    assert s["model"] < s["baseline"] and s["win_rate"] == 1.0


def test_models_round_trip_through_their_files(tmp_path, coins):
    for mod, panel in ((m8, m8.panel_from(coins)), (m8q, m8q.panel_from(coins)), (m10, m10.panel_from(coins)),
                       (m11, m11.panel_from(m11.synthetic_orders(300), None)), (m12, m12.panel_from(*m12.synthetic()))):
        known = panel.filter(pl.col("target").is_not_null())
        fitted = mod.fit(known)
        d = tmp_path / mod.SPEC.name
        d.mkdir()
        mod.save(fitted, d)
        assert (d / "model.json").exists(), "the engine and the registry look for model.json"
        back = mod.restore(d)
        np.testing.assert_allclose(mod.predict(back, known.head(50)), mod.predict(fitted, known.head(50)), rtol=1e-9)


# ---------------------------------------------------------------- the cron run, end to end

def loaders(coins, orders=400):
    led = {o["id"]: o for o in m11.synthetic_orders(orders)}
    return {"m8_direction": lambda: m8.panel_from(coins), "m8_quantiles": lambda: m8q.panel_from(coins),
            "m8_upper": lambda: m8q.panel_from(coins),
            "m10_vol_regime": lambda: m10.panel_from(coins),
            "m11_slippage": lambda: m11.load(ledger=led, base=None),
            "m12_cross_asset": lambda: m12.panel_from(*m12.synthetic())}


def test_train_due_promotes_shadows_reports_and_alerts(root, coins):
    posted = []
    poster = lambda t: (posted.append(t) or True, None)  # noqa: E731
    d = train.run(now_ms=NOW, loaders=loaders(coins), poster=poster)
    by = {e["code"]: e for e in d["models"]}
    assert set(by) == {"M1", "M2", "M7", "M8", "M8q", "M8u", "M10", "M11", "M12"}
    assert by["M7"]["status"] == "retired"
    assert by["M1"]["status"] == "not on this machine"
    # M11 passes its gate and, with no champion, is promoted and published.
    assert by["M11"]["status"] == "shadow" and by["M11"]["champion"]
    assert (root / "models" / "m11_slippage" / by["M11"]["champion"]["version"] / "model.json").exists()
    # M8 on noise fails: no champion, still scored in shadow as a candidate, nothing may use it.
    assert by["M8"]["status"] == "failed its gate" and by["M8"]["champion"] is None
    assert by["M8"]["shadow_model"]["role"] == "candidate" and by["M8"]["live"]["recorded_today"] > 0
    assert by["M8"]["history"] and by["M8"]["drift"]["level"] in ("stable", "shift", "drift")
    # The promotion went out once, to the channel, without em dashes.
    assert len(posted) == 1 and "M11" in posted[0] and "promoted" in posted[0] and chr(0x2014) not in posted[0]
    assert (root / "reports" / "models" / "latest.json").exists()
    js = json.loads((root / "reports" / "models" / "latest.json").read_text())
    assert js["models"] and js["specs"]
    # The lab feed header (docs/LAB-FEEDS.md): Home and Research read the zoo like any other feed.
    assert js["title"] == "Models" and js["status"] in ("ok", "watch", "bad") and js["updated_ms"] == NOW
    assert "zoo models beat their baseline" in js["headline"] and chr(0x2014) not in js["headline"]
    assert {i["label"].split()[0] for i in js["items"]} == set(by)
    m11_item = next(i for i in js["items"] if i["label"].startswith("M11"))
    assert m11_item["status"] == "ok" and m11_item["importance"] == 70
    # M8q's shadow forecasts are three numbers each and are scored as such.
    assert by["M8q"]["live"]["recorded_today"] > 0
    assert "| M11 Slippage of demo market orders | shadow |" in (root / "reports" / "models" / "latest.md").read_text()

    # The next day nothing is due: no retrain, the shadow forecasts are not recorded twice, no repeat alert.
    posted.clear()
    d2 = train.run(now_ms=NOW + DAY_MS, loaders=loaders(coins), poster=poster)
    assert all(s["status"] == "skipped" for s in d2["steps"])
    by2 = {e["code"]: e for e in d2["models"]}
    assert by2["M8"]["live"]["recorded_today"] == 0
    assert posted == []


def test_a_better_challenger_replaces_the_champion_only_on_unseen_rows(root, coins):
    train.run(now_ms=NOW, loaders=loaders(coins, 300), send=False)
    first = registry.champion("m11_slippage")["version"]
    # Eight days later (a Monday, M11's weekday), with many more fills, the retrain is due again.
    d = train.run(now_ms=NOW + 8 * DAY_MS, loaders=loaders(coins, 700), send=False)
    rec = next(x for x in d["steps"] if x["model"] == "M11")
    assert rec["status"] in ("promoted", "rejected", "kept")
    dec = registry.registry_dir("m11_slippage") / "decisions.jsonl"
    rows = [json.loads(x) for x in dec.read_text().splitlines()]
    assert rows[-1]["champion"] == first and rows[-1]["window_rows"] > 0


def test_drift_is_alerted_once(root, coins):
    train.run(now_ms=NOW, loaders=loaders(coins), send=False)
    led = {o["id"]: o for o in m11.synthetic_orders(400)}
    shifted = m11.load(ledger=led, base=None)
    # The last month's orders are ten times larger than anything in training.
    shifted = shifted.with_columns(log_notional=pl.when(pl.col("ts_us") > shifted["ts_us"].max() - 30 * 86_400_000_000)
                                   .then(pl.col("log_notional") + 5).otherwise(pl.col("log_notional")))
    ld = {**loaders(coins), "m11_slippage": lambda: shifted}
    posted = []
    poster = lambda t: (posted.append(t) or True, None)  # noqa: E731
    d = train.run(now_ms=NOW + DAY_MS, loaders=ld, poster=poster, train=False)
    m = next(e for e in d["models"] if e["code"] == "M11")
    assert m["drift"]["level"] == "drift" and m["drift"]["features"][0]["feature"] == "log_notional"
    assert len(posted) == 1 and "outside the trained range" in posted[0]
    posted.clear()
    train.run(now_ms=NOW + 2 * DAY_MS, loaders=ld, poster=poster, train=False)
    assert posted == []


def test_missing_data_is_a_status_not_a_crash(root):
    d = train.run(now_ms=NOW, loaders={n: no_data for n in zoo.ZOO_MODULES}, send=False)
    for e in d["models"]:
        if e["managed_by"] == "zoo":
            assert e["status"] == "waiting for data" and e["status_detail"] == "not in this test"
    assert not (root / "models" / "zoo" / "state.json").read_text().count("last_success_ms")
