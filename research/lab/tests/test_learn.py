"""The learning loop on synthetic data: guardrails, demo-fill costs, champion and challenger, the digest.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import report
from lab.ops import fills, guard, learn, registry

DAY_MS = 86_400_000
HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
NOW = int(datetime(2026, 10, 11, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)  # a Sunday

BASE = {
    "_comment": ["test table"],
    "version": 1,
    "venues": {
        "alpaca": {"label": "Alpaca", "takerBps": 0, "makerBps": 0, "halfSpreadBps": 3, "impactCoeff": 10,
                   "borrowBpsYr": 30, "minNotional": 1, "defaultDepth": 30000,
                   "symbols": {"BTC/USD": {"takerBps": 25, "makerBps": 15, "halfSpreadBps": 1.5, "impactCoeff": 5,
                                           "borrowBpsYr": 0, "minNotional": 10, "defaultDepth": 1000000},
                               "ETH/USD": {"takerBps": 25, "makerBps": 15, "halfSpreadBps": 2.5, "impactCoeff": 6,
                                           "borrowBpsYr": 0, "minNotional": 10, "defaultDepth": 1000000}}},
        "kraken": {"label": "Kraken", "takerBps": 40, "makerBps": 25, "halfSpreadBps": 25, "impactCoeff": 25,
                   "borrowBpsYr": 0, "minNotional": 10, "defaultDepth": 15000, "symbols": {}},
    },
}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    """Data root, reports and the sweep's folder in a temp directory; no engine."""
    data = tmp_path / "data"
    data.mkdir()
    for mod in (fills, guard, registry, learn):
        monkeypatch.setattr(mod, "ROOT", data)
    monkeypatch.setattr(report, "REPORTS", data / "reports")
    monkeypatch.setenv("PYTHIA_AGENT_OUT", str(data / "lab-cache"))
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.delenv("PYTHIA_LEARN_ORDERS_FILE", raising=False)
    monkeypatch.delenv("PYTHIA_COSTS_BASE", raising=False)
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)
    (data / "costs").mkdir()
    (data / "costs" / "base.json").write_text(json.dumps(BASE))
    guard.WRITTEN.clear()
    return data


def order(i: int, sym="BTC/USD", kind="market", status="filled", route="demo", realised=3.0, modelled=1.6,
          ts=None, px=60000.0, qty=0.01) -> dict:
    return {"id": f"o{i}", "ts": ts if ts is not None else NOW - DAY_MS + i * 1000, "strategyId": "lab:tsmom",
            "marketId": f"crypto:{sym}", "venue": "crypto", "side": "buy", "type": kind, "qty": qty,
            "status": status, "filledQty": qty if status == "filled" else 0.0, "avgFillPrice": px,
            "mode": "live", "route": route, "realisedSlippageBps": realised if status == "filled" else None,
            "modelledSlippageBps": modelled}


# ---------------------------------------------------------------- guardrails

def test_writes_outside_the_allowlist_are_refused(root):
    for p in (root / "autopilot" / "state.json", root / "paper" / "tsmom" / "state.json",
              root / "costs" / "base.json", root / "models" / "other" / "x.json", root / "reports" / "forward" / "x"):
        with pytest.raises(guard.GuardError):
            guard.write_text(p, "x")
    guard.write_text(root / "learn" / "ok.txt", "x")
    guard.write_text(root / "costs" / "learned.json", "{}")
    assert (root / "learn" / "ok.txt").read_text() == "x"


def test_a_published_model_is_never_overwritten(root, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "card.json").write_text("{}")
    guard.copy_tree(src, root / "models" / "vol_1h" / "2026-10-11")
    with pytest.raises(guard.GuardError):
        guard.copy_tree(src, root / "models" / "vol_1h" / "2026-10-11")


def test_only_get_api_state_is_called():
    assert guard.read_only_url("http://127.0.0.1:8788/api/state")
    for bad in ("http://127.0.0.1:8788/api/autopilots/arm", "http://127.0.0.1:8788/api/live/arm",
                "http://127.0.0.1:8788/api/state?arm=1", "file:///etc/passwd", "http://127.0.0.1:8788/api/settings"):
        with pytest.raises(guard.GuardError):
            guard.read_only_url(bad)


def test_the_loop_source_has_no_way_to_command_the_engine():
    here = Path(guard.__file__).parent
    for f in ("learn.py", "fills.py", "registry.py", "guard.py"):
        src = (here / f).read_text(encoding="utf-8")
        for word in ('"POST"', '"PUT"', '"DELETE"', "method=\"P", "/api/live", "/api/autopilot", "/api/settings",
                     "/api/risk", "/api/strategies", "/api/vault"):
            assert word not in src, f"{f} mentions {word}"


def test_cost_violations_catch_fees_bounds_and_new_symbols():
    ok = json.loads(json.dumps(BASE))
    ok["venues"]["alpaca"]["symbols"]["BTC/USD"]["halfSpreadBps"] = 3.0
    assert guard.cost_violations(BASE, ok) == []
    fee = json.loads(json.dumps(ok))
    fee["venues"]["alpaca"]["symbols"]["BTC/USD"]["takerBps"] = 5
    assert any("takerBps" in v for v in guard.cost_violations(BASE, fee))
    venue = json.loads(json.dumps(ok))
    venue["venues"]["kraken"]["takerBps"] = 10
    assert any("kraken.takerBps" in v for v in guard.cost_violations(BASE, venue))
    far = json.loads(json.dumps(ok))
    far["venues"]["alpaca"]["symbols"]["BTC/USD"]["halfSpreadBps"] = 40.0
    assert any("more than" in v for v in guard.cost_violations(BASE, far))
    nan = json.loads(json.dumps(ok))
    nan["venues"]["alpaca"]["symbols"]["BTC/USD"]["impactCoeff"] = float("nan")
    assert guard.cost_violations(BASE, nan)
    new = json.loads(json.dumps(ok))
    new["venues"]["alpaca"]["symbols"]["DOGE/USD"] = {"halfSpreadBps": 5}
    assert any("added" in v for v in guard.cost_violations(BASE, new))


# ---------------------------------------------------------------- demo fills and costs

def test_the_ledger_keeps_finished_demo_orders_once(root):
    orders = [order(1), order(2, status="pending"), order(3, route="paper"), order(4, route="live"),
              order(5, kind="limit", status="cancelled"),
              order(6, status="partial", ts=NOW - 2 * DAY_MS), order(7, status="partial", ts=NOW - 1000)]
    assert fills.update_ledger(orders, NOW) == 3   # 1, 5 and the day-old partial 6
    assert fills.update_ledger(orders, NOW) == 0   # nothing twice
    assert set(fills.read_ledger()) == {"o1", "o5", "o6"}


def test_fill_rates_and_slippage_per_symbol():
    led = {}
    for i in range(10):
        led[f"m{i}"] = order(i, realised=2.0 + i)
    for i in range(4):
        led[f"l{i}"] = order(100 + i, kind="limit", realised=-1.0)
    for i in range(6):
        led[f"c{i}"] = order(200 + i, kind="limit", status="cancelled")
    led["x"] = order(300, status="rejected")
    m = fills.measure(led, BASE)["BTC/USD"]
    assert m["taker_fills"] == 10 and m["maker_fills"] == 4
    assert m["maker_fill_rate"] == pytest.approx(0.4) and m["maker_orders"] == 10
    assert m["taker_fill_rate"] == pytest.approx(10 / 11)
    assert m["median_realised_bps"] == pytest.approx(6.5)
    # 600 USD against 1M depth: 1.5 + 5 * sqrt(0.0006)
    assert m["median_base_bps"] == pytest.approx(1.5 + 5 * np.sqrt(600 / 1e6))


def test_fewer_than_30_fills_never_change_the_costs(root):
    orders = [order(i, realised=4.0) for i in range(fills.MIN_FILLS - 1)]
    out = fills.run(orders, NOW)
    learned = json.loads((root / "costs" / "learned.json").read_text())
    assert learned["venues"]["alpaca"]["symbols"]["BTC/USD"]["halfSpreadBps"] == 1.5
    assert out["decisions"]["BTC/USD"]["status"].startswith("collecting")
    assert learned["measured"]["alpaca"]["BTC/USD"]["taker_fills"] == fills.MIN_FILLS - 1


def test_30_fills_scale_spread_and_impact_within_bounds(root):
    out = fills.run([order(i, realised=3.2) for i in range(40)], NOW)
    d = out["decisions"]["BTC/USD"]
    assert d["status"] == "applied"
    base_cost = 1.5 + 5 * np.sqrt(600 / 1e6)
    assert d["factor"] == pytest.approx(3.2 / base_cost, rel=1e-6)
    learned = json.loads((root / "costs" / "learned.json").read_text())
    btc = learned["venues"]["alpaca"]["symbols"]["BTC/USD"]
    assert btc["halfSpreadBps"] == pytest.approx(1.5 * d["factor"], rel=1e-2)
    assert btc["takerBps"] == 25 and btc["makerBps"] == 15  # fees never move
    assert learned["venues"]["kraken"] == BASE["venues"]["kraken"]
    assert guard.cost_violations(BASE, {k: v for k, v in learned.items() if k != "measured"}) == []
    # A huge measured slippage is capped at the factor bound, not taken at face value.
    out = fills.run([order(1000 + i, realised=500.0) for i in range(200)], NOW)
    assert out["decisions"]["BTC/USD"]["factor"] < guard.COST_MAX_FACTOR
    assert out["violations"] == []


def test_a_previous_calibration_survives_a_lost_ledger(root):
    fills.run([order(i, realised=3.2) for i in range(40)], NOW)
    applied = json.loads((root / "costs" / "learned.json").read_text())["venues"]["alpaca"]["symbols"]["BTC/USD"]
    fills.ledger_path().unlink()
    fills.run([order(900 + i, realised=9.0) for i in range(3)], NOW)
    again = json.loads((root / "costs" / "learned.json").read_text())["venues"]["alpaca"]["symbols"]["BTC/USD"]
    assert again["halfSpreadBps"] == applied["halfSpreadBps"]


def test_without_a_base_table_only_the_measurement_is_written(root):
    (root / "costs" / "base.json").unlink()
    out = fills.run([order(i) for i in range(40)], NOW)
    assert out["learned_file"] is None and "no base cost table" in out["note"]
    assert not (root / "costs" / "learned.json").exists()
    assert (root / "learn" / "costs_measured.json").exists()


# ---------------------------------------------------------------- champion and challenger

FEATS = ["f1", "f2"]


def make_vol_model(folder: Path, train_to_us: int, passed: bool = True, holdout: pl.DataFrame | None = None):
    folder.mkdir(parents=True)
    (folder / "card.json").write_text(json.dumps({"name": "vol_1h", "features": FEATS, "train_to_us": train_to_us,
                                                  "residual_var": 0.1, "qlike_gain_vs_har": 0.1, "dm_p_vs_har": 0.001}))
    (folder / "model.json").write_text("{}")
    (folder / "challenger.json").write_text(json.dumps({"passed": passed, "why": "test"}))
    if holdout is not None:
        holdout.write_parquet(folder / "holdout.parquet")


def vol_holdout(start_us: int, hours: int, noise: float, seed=1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    true = np.exp(rng.normal(-8, 1, hours))
    target = true * rng.chisquare(4, hours) / 4
    challenger = true * np.exp(rng.normal(0, noise, hours))
    return pl.DataFrame({"ts_us": start_us + np.arange(hours) * HOUR_US, "symbol": ["BTC"] * hours,
                         "target": target, "challenger": challenger,
                         "f1": np.log(true), "f2": rng.normal(size=hours)})


def champion_from_f1(noise: float, seed=2):
    rng = np.random.default_rng(seed)
    return lambda X: np.exp(X[:, 0] + rng.normal(0, noise, len(X)))


def test_no_champion_and_a_passing_gate_promotes(root):
    cand = registry.candidates_dir("vol_1h") / "2026-10-11"
    make_vol_model(cand, 0, holdout=vol_holdout(0, 100, 0.1))
    rec = registry.decide("vol_1h", cand, NOW)
    assert rec["decision"] == "promoted" and rec["published"] == "2026-10-11"
    assert (root / "models" / "vol_1h" / "2026-10-11" / "card.json").exists()
    assert not (root / "models" / "vol_1h" / "2026-10-11" / "holdout.parquet").exists()
    champ = json.loads((registry.registry_dir("vol_1h") / "champion.json").read_text())
    assert champ["version"] == "2026-10-11"


def test_a_challenger_that_fails_its_gate_is_rejected(root):
    cand = registry.candidates_dir("vol_1h") / "2026-10-11"
    make_vol_model(cand, 0, passed=False, holdout=vol_holdout(0, 100, 0.1))
    rec = registry.decide("vol_1h", cand, NOW)
    assert rec["decision"] == "rejected" and "gate" in rec["why"]
    assert not (root / "models" / "vol_1h").exists()


def test_better_out_of_sample_promotes_and_worse_keeps_the_champion(root):
    t0 = 1_700_000_000 * 1_000_000
    make_vol_model(root / "models" / "vol_1h" / "2026-09-01", t0)
    hold = vol_holdout(t0 + 2 * HOUR_US, 24 * 100, noise=0.05)
    good = registry.candidates_dir("vol_1h") / "2026-10-04"
    make_vol_model(good, t0 + 24 * 100 * HOUR_US, holdout=hold)
    rec = registry.decide("vol_1h", good, NOW, champion_predict=champion_from_f1(0.8))
    assert rec["decision"] == "promoted", rec["why"]
    assert rec["challenger_score"] < rec["champion_score"]
    assert registry.latest_version(root / "models" / "vol_1h").name == "2026-10-04"

    # The new champion is the bar now; a noisier challenger does not replace it.
    bad = registry.candidates_dir("vol_1h") / "2026-10-11"
    hold2 = vol_holdout(t0 + 24 * 101 * HOUR_US, 24 * 100, noise=0.8, seed=5)
    make_vol_model(bad, t0, holdout=hold2)
    rec2 = registry.decide("vol_1h", bad, NOW + 7 * DAY_MS, champion_predict=champion_from_f1(0.05))
    assert rec2["decision"] == "rejected" and rec2["champion"] == "2026-10-04"
    assert registry.latest_version(root / "models" / "vol_1h").name == "2026-10-04"
    lines = (registry.registry_dir("vol_1h") / "decisions.jsonl").read_text().splitlines()
    assert [json.loads(x)["decision"] for x in lines] == ["promoted", "rejected"]


def test_too_short_a_window_keeps_the_champion(root):
    t0 = 1_700_000_000 * 1_000_000
    make_vol_model(root / "models" / "vol_1h" / "2026-09-01", t0 + 100 * HOUR_US)
    cand = registry.candidates_dir("vol_1h") / "2026-10-11"
    make_vol_model(cand, t0, holdout=vol_holdout(t0, 110, 0.01))
    rec = registry.decide("vol_1h", cand, NOW, champion_predict=champion_from_f1(1.0))
    assert rec["decision"] == "kept" and "never saw" in rec["why"]


def test_a_promotion_sorts_after_the_running_version(root):
    t0 = 1_700_000_000 * 1_000_000
    make_vol_model(root / "models" / "vol_1h" / "2026-10-11", t0)
    cand = registry.candidates_dir("vol_1h") / "2026-10-11"
    make_vol_model(cand, t0, holdout=vol_holdout(t0 + 2 * HOUR_US, 24 * 100, 0.05))
    rec = registry.decide("vol_1h", cand, NOW, champion_predict=champion_from_f1(0.8))
    assert rec["decision"] == "promoted" and rec["published"] > "2026-10-11"
    assert registry.latest_version(root / "models" / "vol_1h").name == rec["published"]


def picks_holdout(start_us: int, days: int, skill: float, seed=3) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        x = rng.normal(size=40)
        fwd = 0.3 * x + rng.normal(size=40)
        rows.append(pl.DataFrame({"ts_us": [start_us + d * DAY_US] * 40, "symbol": [f"C{i}" for i in range(40)],
                                  "target": fwd, "challenger": skill * x + rng.normal(size=40), "f1": x,
                                  "f2": rng.normal(size=40)}))
    return pl.concat(rows)


def test_m2_is_judged_by_rank_ic_on_days_the_champion_never_saw(root):
    t0 = 1_700_000_000 * 1_000_000
    champ = root / "models" / "picks_7d" / "2026-09-01"
    champ.mkdir(parents=True)
    (champ / "card.json").write_text(json.dumps({"features": FEATS, "train_to_us": t0}))
    (champ / "model.json").write_text("{}")
    cand = registry.candidates_dir("picks_7d") / "2026-10-11"
    cand.mkdir(parents=True)
    (cand / "card.json").write_text(json.dumps({"features": FEATS, "train_to_us": t0 + 60 * DAY_US,
                                                "out_of_sample": {"rank_ic": 0.1, "rank_ic_t": 4.0}}))
    (cand / "model.json").write_text("{}")
    picks_holdout(t0, 60, skill=3.0).write_parquet(cand / "holdout.parquet")
    weak = lambda X: X[:, 1]  # the champion ranks on noise  # noqa: E731
    rec = registry.decide("picks_7d", cand, NOW, champion_predict=weak)
    assert rec["decision"] == "promoted"
    assert rec["window_days"] == 60 - 8  # days 8 to 59: the champion's label horizon is embargoed
    assert rec["challenger_score"] > 0.1 > abs(rec["champion_score"])


def test_m2_gate_needs_a_significant_walk_forward_ic(root):
    cand = registry.candidates_dir("picks_7d") / "2026-10-11"
    cand.mkdir(parents=True)
    (cand / "card.json").write_text(json.dumps({"out_of_sample": {"rank_ic": 0.01, "rank_ic_t": 1.2}}))
    (cand / "model.json").write_text("{}")
    assert registry.decide("picks_7d", cand, NOW)["decision"] == "rejected"


# ---------------------------------------------------------------- schedule, evidence, autopilots

def test_schedule_waits_for_period_and_weekday():
    st = {"steps": {}}
    assert learn.due("vol", st, NOW)[0]                # never run
    assert learn.due("costs", st, NOW)[0]              # nightly
    learn.mark(st, "vol", NOW, True, "ok")
    assert not learn.due("vol", st, NOW + DAY_MS)[0]
    assert learn.due("vol", st, NOW + 7 * DAY_MS)[0]   # the next Sunday
    assert not learn.due("vol", st, NOW + 8 * DAY_MS)[0]  # a Monday: waits for Sunday
    learn.mark(st, "m2", NOW, False, "boom")
    assert not learn.due("m2", st, NOW + 3600_000)[0]  # no retry within a day
    assert learn.due("m2", st, NOW + DAY_MS)[0]        # then again, it never succeeded


def write_evidence(root: Path, ms: int, books: dict):
    d = root / "reports" / "forward"
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence.json").write_text(json.dumps({"generated_ms": ms, "books": books, "autopilots": {}}))


def test_evidence_history_tracks_status_changes(root):
    changes: list[dict] = []
    write_evidence(root, NOW - 2 * DAY_MS, {"tsmom": {"status": "early", "days": 8, "return_pct": 1.0}})
    learn.step_evidence(NOW - 2 * DAY_MS, changes)
    write_evidence(root, NOW - DAY_MS, {"tsmom": {"status": "ok", "days": 10, "return_pct": 2.0}})
    learn.step_evidence(NOW - DAY_MS, changes)
    write_evidence(root, NOW, {"tsmom": {"status": "ok", "days": 11, "return_pct": 2.5}})
    out = learn.step_evidence(NOW, changes)
    assert [c["what"] for c in changes] == ["book:tsmom: first forward evidence (early)", "book:tsmom: early -> ok"]
    s = out["strategies"]["book:tsmom"]
    assert s["status"] == "ok" and s["previous"] == "early" and s["ok_last30"] == 2 and s["snapshots"] == 3
    # Running twice on the same report does not add a snapshot.
    learn.step_evidence(NOW, changes)
    assert len(learn.read_history(root / "learn" / "evidence_history.jsonl")) == 3


def test_autopilot_pnl_against_btc():
    start = NOW - 3 * DAY_MS
    state = {"autopilots": [{"config": {"id": "ap1", "name": "Demo", "mode": "live"}, "state": "running",
                             "startedMs": start, "startCapital": 1000.0, "equity": 1100.0,
                             "history": [[start, 1000.0], [NOW - DAY_MS - 1, 1050.0], [NOW, 1100.0]]}]}
    prices = {start // 60_000 * 60_000: 50_000.0, (NOW - DAY_MS) // 60_000 * 60_000: 52_000.0,
              NOW // 60_000 * 60_000: 52_000.0}
    rows = learn.autopilot_pnl(state, NOW, lambda ms: prices.get(ms))
    a = rows[0]
    assert a["pnl_total_pct"] == pytest.approx(10.0) and a["btc_total_pct"] == pytest.approx(4.0)
    assert a["vs_btc_total_pts"] == pytest.approx(6.0)
    assert a["pnl_day_pct"] == pytest.approx(50 / 1050 * 100) and a["btc_day_pct"] == pytest.approx(0.0)


def test_today_is_unknown_when_the_curve_has_no_point_near_a_day_ago():
    """The engine's curve of 2026-10-20 held its start and the last 19 hours:
    the equity "a day ago" was the start capital, so today read the same as
    since start. A point more than three hours before a day ago is no day ago."""
    start = NOW - 5 * DAY_MS
    hist = [[start, 20_000.0]] + [[NOW - h * 3_600_000, 20_050.0] for h in range(19, -1, -1)]
    state = {"autopilots": [{"config": {"id": "ap1", "name": "Auto"}, "state": "running", "startedMs": start,
                             "startCapital": 20_000.0, "equity": 20_059.0, "history": hist, "orders": 14}]}
    a = learn.autopilot_pnl(state, NOW, lambda ms: 60_000.0)[0]
    assert a["pnl_total_pct"] == pytest.approx(59 / 20_000 * 100)
    assert a["pnl_day_pct"] is None, "not the change since start"
    assert a["orders"] == 14
    # A point two hours before a day ago still counts.
    state["autopilots"][0]["history"] = [[start, 20_000.0], [NOW - DAY_MS - 2 * 3_600_000, 20_040.0], [NOW, 20_059.0]]
    assert learn.autopilot_pnl(state, NOW, lambda ms: 60_000.0)[0]["pnl_day_pct"] == pytest.approx(19 / 20_040 * 100)
    # Younger than a day: today is since start.
    state["autopilots"][0].update(startedMs=NOW - 3_600_000, history=[[NOW - 3_600_000, 20_000.0]])
    a = learn.autopilot_pnl(state, NOW, lambda ms: 60_000.0)[0]
    assert a["pnl_day_pct"] == pytest.approx(a["pnl_total_pct"])


# ---------------------------------------------------------------- the whole night

def fake_runner(root: Path, t0: int):
    calls = []

    def run(args, env, timeout):
        calls.append(args)
        if args[0] == "lab.experiments.vol":
            d = Path(args[-1]) / "2026-10-11"
            make_vol_model(d, t0 + 24 * 100 * HOUR_US, holdout=vol_holdout(t0 + 2 * HOUR_US, 24 * 100, 0.05))
            return 0, "ok"
        if args[0] == "lab.experiments.picks":
            return 1, "Traceback: no data"
        if args[0] == "lab.experiments.families":
            out = Path(env["PYTHIA_AGENT_OUT"])
            (out / "reports").mkdir(parents=True)
            (out / "runs").mkdir(parents=True)
            (out / "runs" / "breakout.json").write_text("[]")
            (out / "reports" / "families_summary.json").write_text(json.dumps({"n_variants": 100, "picks": [
                {"family": "breakout", "sub": "top10", "variant": "Donchian 20/10 · top 10 liquid", "passes": True,
                 "verdict": "passes", "deflated_p": 0.97, "oos_sharpe_41bps": 1.0, "oos_sharpe_15bps": 1.2,
                 "oos_max_dd_41bps": 0.3}]}))
            return 0, "ok"
        return 2, "unknown"
    return run, calls


def snapshot(root: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_a_full_night_writes_the_digest_and_touches_nothing_else(root, monkeypatch, tmp_path):
    t0 = 1_700_000_000 * 1_000_000
    make_vol_model(root / "models" / "vol_1h" / "2026-09-01", t0)
    out = root / "lab-cache"
    (out / "reports").mkdir(parents=True)
    (out / "reports" / "families_summary.json").write_text(json.dumps({"n_variants": 100, "picks": [
        {"family": "breakout", "sub": "top10", "variant": "Donchian 20/10 · top 10 liquid", "passes": False,
         "verdict": "fails: deflated p 0.90 <= 0.95", "deflated_p": 0.9, "oos_sharpe_41bps": 0.8,
         "oos_sharpe_15bps": 1.0, "oos_max_dd_41bps": 0.3}]}))
    # Things the loop must never touch.
    (root / "autopilot").mkdir()
    (root / "autopilot" / "state.json").write_text('{"live": {"armed": false}}')
    (root / "paper" / "tsmom").mkdir(parents=True)
    (root / "paper" / "tsmom" / "journal.csv").write_text("date,equity\n2026-10-10,10000\n")
    write_evidence(root, NOW, {"tsmom": {"status": "ok", "days": 12, "return_pct": 1.0}})
    exported = tmp_path / "state.json"
    start = NOW - 5 * DAY_MS
    exported.write_text(json.dumps({
        "orders": [order(i, realised=2.0) for i in range(35)],
        "autopilots": [{"config": {"id": "ap1", "name": "Breakout demo", "mode": "live"}, "state": "running",
                        "startedMs": start, "startCapital": 1000.0, "equity": 1020.0,
                        "history": [[start, 1000.0], [NOW, 1020.0]]}]}))
    monkeypatch.setenv("PYTHIA_LEARN_ORDERS_FILE", str(exported))
    protected = {k: v for k, v in snapshot(root).items()
                 if "/autopilot/" in k or "/paper/" in k or k.endswith("base.json") or "/reports/forward/" in k}

    runner, calls = fake_runner(root, t0)
    d = learn.run(NOW, runner=runner, price_at=lambda ms: 50_000.0, champion_predict=champion_from_f1(0.8))

    assert [c[0] for c in calls] == ["lab.experiments.families", "lab.experiments.vol", "lab.experiments.picks"]
    status = {s["step"]: s["status"] for s in d["steps"]}
    assert status == {"costs": "ok", "evidence": "ok", "sweep": "ok", "vol": "ok", "m2": "failed"}
    assert any(x["model"] == "vol_1h" and x["decision"] == "promoted" for x in d["decisions"])
    assert any(c["area"] == "gates" and "now passes" in c["what"] for c in d["changes"])
    assert any(c["area"] == "costs" and "BTC/USD" in c["what"] for c in d["changes"])
    assert d["autopilots"][0]["pnl_total_pct"] == pytest.approx(2.0)
    assert d["autopilots"][0]["vs_btc_total_pts"] == pytest.approx(2.0)
    assert "promoted vol_1h" in d["headline"] and "failed: m2" in d["headline"]
    assert d["guardrails"]["refused"] == []

    latest = json.loads((root / "reports" / "learn" / "latest.json").read_text())
    assert latest["headline"] == d["headline"]
    md = (root / "reports" / "learn" / "latest.md").read_text()
    assert "Autopilots against BTC" in md and "\u2014" not in md
    # Every file written is inside the allowlist, and the protected ones are untouched.
    for p in d["guardrails"]["written"]:
        guard.check_write(Path(p))
    after = snapshot(root)
    assert {k: after.get(k) for k in protected} == protected
    published = json.loads((out / "reports" / "families_summary.json").read_text())
    assert published["picks"][0]["passes"] is True
    backups = list((root / "models" / "registry" / "families_sweep" / "previous").rglob("families_summary.json"))
    assert len(backups) == 1

    # The next night nothing heavy is due, and the failed M2 retrain waits a day.
    d2 = learn.run(NOW + 3600_000, runner=runner, price_at=lambda ms: 50_000.0)
    status2 = {s["step"]: s["status"] for s in d2["steps"]}
    assert status2["vol"] == "not due" and status2["sweep"] == "not due" and status2["m2"] == "not due"
    assert len(calls) == 3


def test_a_sweep_with_fewer_variants_is_not_published(root):
    old = {"n_variants": 100, "picks": [{"family": "a", "sub": "x", "variant": "v", "passes": False,
                                         "deflated_p": 0.5, "oos_sharpe_41bps": 0.1, "oos_sharpe_15bps": 0.2}]}
    new = {"n_variants": 40, "picks": [{"family": "a", "sub": "x", "variant": "v", "passes": True,
                                        "deflated_p": 0.99, "oos_sharpe_41bps": 0.1, "oos_sharpe_15bps": 0.2}]}
    assert any("fewer variants" in p for p in learn.sweep_problems(old, new))
    assert learn.sweep_problems(old, {"picks": []}) == ["the fresh sweep wrote no picks"]
    assert learn.gate_changes(old, {**new, "n_variants": 100})[0]["now"] is True


def test_the_engine_down_still_gives_a_digest(root):
    d = learn.run(NOW, train=False, price_at=lambda ms: None)
    assert d["engine"]["reachable"] is False
    assert {s["step"]: s["status"] for s in d["steps"]}["sweep"] == "skipped"
    assert (root / "reports" / "learn" / "latest.json").exists()
