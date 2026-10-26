"""A1: the model zoo, the selector, the allocator and the study's tests (results/pumpfun_adaptive_a1_prereg.md)."""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from lab.pumpfun_rt import adaptive_a1 as AA
from lab.pumpfun_rt import allocator as A
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import selector as S
from lab.pumpfun_rt import zoo as Z

DAY = 86_400_000
T0 = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)


def data(n=3000, k=6, seed=0, drift=False):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, k))
    w = np.linspace(1.5, 0.0, k)
    z = X @ w - 1.0
    if drift:                                       # the sign of the first feature flips halfway
        z = np.where(np.arange(n) < n // 2, z, z - 3.0 * X[:, 0])
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(float)
    return X, y


def ctx(X, y, family="decision"):
    return {"label": "win30", "family": family, "features": [f"f{i}" for i in range(X.shape[1])],
            "params": dict(M.PARAMS, n_estimators=40, min_child_samples=20)}


# ---------------------------------------------------------------- the zoo

def test_registry_and_kinds():
    assert set(Z.MEMBERS) == {"lgb", "logit", "hgb", "online", "hazard"}
    assert "hazard" not in Z.members_for("any") and "hazard" in Z.members_for("exit")
    assert Z.members_for("any", ["logit", "online"]) == ["logit", "online"]
    assert Z.BASELINE in Z.MEMBERS and Z.INCUMBENT in Z.MEMBERS


@pytest.mark.parametrize("name", ["lgb", "logit", "hgb", "online"])
def test_member_interface(name):
    X, y = data()
    X[::7, 2] = np.nan                               # missing values are allowed
    X[:, 5] = np.nan                                 # and a column with none at all
    m = Z.make(name).fit(X[:2000], y[:2000], ctx(X, y))
    p = m.predict_proba(X[2000:])
    assert p.shape == (1000,) and np.all((p >= 0) & (p <= 1))
    assert M.auc(p, y[2000:]) > 0.7
    ex = m.explain([f"f{i}" for i in range(6)], 3)
    assert isinstance(ex, list) and len(ex) <= 3
    if name in ("logit", "online", "lgb"):
        assert ex[0][0] == "f0"


def test_member_one_class_is_the_base_rate():
    X, _ = data(600)
    y = np.zeros(600)
    for name in ("logit", "hgb", "online"):
        p = Z.make(name).fit(X, y, ctx(X, y)).predict_proba(X[:5])
        assert np.allclose(p, 0.0)


def test_hazard_competing_risks():
    rng = np.random.default_rng(1)
    n = 3000
    X = rng.normal(size=(n, 3))
    up = rng.random(n) < 1 / (1 + np.exp(-2 * X[:, 0]))
    dur = np.where(up, rng.uniform(5, 200, n), rng.uniform(0, 60, n))
    ret = np.where(up, 0.3, -0.2)
    y = up.astype(float)
    c = dict(ctx(X, y, "select"), dur=dur[:2000], ret=ret[:2000])
    m = Z.make("hazard").fit(X[:2000], y[:2000], c)
    p = m.predict_proba(X[2000:])
    assert np.all((p >= 0) & (p <= 1)) and M.auc(p, y[2000:]) > 0.75
    assert abs(p.mean() - y[2000:].mean()) < 0.08
    assert m.explain(["a", "b", "c"], 1)[0][0] == "a"
    assert list(Z.Hazard.intervals(np.array([-3.0, 0.0, 9.9, 10.0, 299.0, 301.0, 5000.0]))) == [0, 0, 0, 1, 4, 5, 5]


def test_online_learns_only_known_labels():
    X, y = data(4000, drift=True)
    t = T0 + np.arange(4000) * 60_000.0
    m = Z.make("online").fit(X[:500], y[:500], ctx(X, y))
    frozen = m.stream(X[500:], t[500:], np.full(3500, np.inf), y[500:], 3_600_000)
    m2 = Z.make("online").fit(X[:500], y[:500], ctx(X, y))
    assert np.allclose(frozen, m2.predict_proba(X[500:]))      # no label known: nothing learnt
    live = m2.stream(X[500:], t[500:], t[500:] + 30 * 60_000, y[500:], 3_600_000)
    late = slice(3000, 3500)
    assert M.logloss(live[late], y[500:][late]) < M.logloss(frozen[late], y[500:][late])


# ---------------------------------------------------------------- the selector

def hist(losses: list[dict], se=0.001):
    out = []
    for i, ls in enumerate(losses):
        out.append({"day": f"d{i:02d}", "n": 100, "loss": ls,
                    "se": {a: {b: se for b in ls if b != a} for a in ls}})
    return out


def test_evidence_rule_needs_five_days_beyond_the_band():
    base = {"lgb": 0.50, "logit": 0.52, "hgb": 0.48}
    four = hist([base] * 4)
    assert S.choose(four)["pick"] == "lgb"
    five = hist([base] * 5)
    ch = S.choose(five)
    assert ch["pick"] == "hgb" and ch["picks"] == ["lgb"] * 5 and ch["changes"][0]["to"] == "hgb"
    # ahead, but within the band: no takeover
    assert S.choose(hist([base] * 6, se=0.05))["pick"] == "lgb"
    # one day behind among the last five: no takeover
    mixed = [base] * 4 + [{"lgb": 0.50, "logit": 0.52, "hgb": 0.51}] + [base] * 4
    assert S.choose(hist(mixed))["pick"] == "lgb"


def test_retirement_against_the_baseline():
    ls = [{"lgb": 0.60, "logit": 0.50, "online": 0.55}] * 7
    ch = S.choose(hist(ls, se=1.0))                  # nobody gets ahead by the band
    assert set(ch["retired"]) == {"lgb", "online"} and "logit" not in ch["retired"]
    assert ch["pick"] == "logit" and ch["changes"][0]["why"] == "retired"
    ch6 = S.choose(hist(ls[:6], se=1.0))
    assert ch6["retired"] == {} and ch6["pick"] == "lgb"


def test_blend_weights_and_calibration():
    rng = np.random.default_rng(2)
    y = (rng.random(4000) < 0.3).astype(float)
    good = np.clip(0.3 + 0.5 * (y - 0.3) + rng.normal(0, 0.05, 4000), 0.01, 0.99)
    noise = rng.uniform(0.01, 0.99, 4000)
    w = S.blend_weights(np.column_stack([noise, good]), y)
    assert np.all(w >= 0) and abs(w.sum() - 1) < 1e-9 and w[1] > 0.8
    assert S.calibrator(good[:100], y[:100]) is None
    cal = S.calibrator(good, y)
    p = cal.predict(np.array([0.0, 1.0]))
    assert p.min() >= S.CAL_BOUND and p.max() <= 1 - S.CAL_BOUND


def test_selected_uses_only_prior_days():
    rng = np.random.default_rng(3)
    mk = lambda d, n=400: {"day": d, "y": (rng.random(n) < 0.3).astype(float), "t": np.zeros(n),
                           "regime": np.full(n, "hot", dtype=object),
                           "p": {"lgb": rng.uniform(0, 1, n).astype(np.float32),
                                 "logit": np.full(n, 0.3, dtype=np.float32)}}
    d1, d2 = mk("a"), mk("b")
    p, info = S.selected(d2, [], "lgb")
    assert not info["calibrated"] and np.allclose(p, d2["p"]["lgb"])
    p, info = S.selected(d2, [d1], "lgb")
    assert info["calibrated"]
    assert S.BLEND not in S.with_blend(d2, [])
    assert S.BLEND in S.with_blend(d2, [d1]) and S.BLEND not in S.with_blend(d2, [d1], ["lgb", "logit"])


def test_rug_share_is_causal():
    t = np.array([0.0, 10_000, 20_000, 30_000]) + T0
    tab = {"t": t, "entry": np.array([0, 0, 5, 0.0]), "rug": np.array([1, 0, 1, 1.0])}
    at = np.array([T0 + 65_000, T0 + 75_000, T0 + 95_000, T0 + 60_000 + 3_600_000 + 5_000])
    s = S.rug_share(tab, at)
    assert s[0] == 1.0                               # only the first window has ended
    assert s[1] == 0.5 and np.isclose(s[2], 2 / 3)   # the entry-5 row never counts
    assert np.isclose(s[3], 0.5)                     # the first has left the hour
    assert np.isnan(S.rug_share(tab, np.array([T0 + 1.0]))[0])


def test_regimes():
    rng = np.random.default_rng(4)
    tr = rng.normal(size=(900, 3))
    r = S.regime_of(tr, np.array([[-5.0, -5, -5], [0, 0, 0], [5, 5, 5], [np.nan] * 3]))
    assert list(r) == ["cold", "normal", "hot", ""]


class Spy(Z.Member):
    NAME = "spy"
    seen: list = []

    def fit(self, X, y, ctx):
        self._base(y)
        Spy.seen.append((float(ctx["t"].max()), len(y)))
        return self

    def predict_proba(self, X):
        return np.full(len(X), self.base)


def table(days=4, per_day=600, h_ms=600_000, seed=5):
    X, y = data(days * per_day, seed=seed)
    t = T0 + np.sort(np.random.default_rng(seed).uniform(0, days * DAY, days * per_day))
    return {"label": "win30", "family": "decision", "kind": "any", "t": t, "y": y, "X": X,
            "features": [f"f{i}" for i in range(X.shape[1])], "h_ms": h_ms, "heat": X[:, :1]}


def test_walk_is_purged(monkeypatch):
    monkeypatch.setitem(Z.MEMBERS, "spy", Spy)
    Spy.seen = []
    tab = table()
    out = S.walk(tab, ["2026-10-21", "2026-10-22"], ["spy"], log=lambda *_: None)
    assert [x["day"] for x in out] == ["2026-10-21", "2026-10-22"]
    for (tmax, _), d in zip(Spy.seen, ["2026-10-21", "2026-10-22"]):
        assert tmax + tab["h_ms"] < S.day_start(d)
    assert all(len(x["y"]) == len(x["p"]["spy"]) for x in out)


def test_run_grows_the_history_and_never_retests(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LABELS", {"win30": "decision"})
    monkeypatch.setitem(Z.MEMBERS, "spy", Spy)
    tab = table(days=4)
    monkeypatch.setattr(S, "table_for", lambda label, rows, sel: tab)
    monkeypatch.setattr(Z, "members_for", lambda kind, names=None: ["spy", "logit"])
    now = T0 + 4 * DAY + 3_600_000
    s1 = S.run(None, None, now, tmp_path, log=lambda *_: None)
    st = json.loads((tmp_path / "state.json").read_text())
    days = sorted(st["history"]["win30"])
    assert days == ["2026-10-21", "2026-10-22", "2026-10-23"]
    assert s1["labels"]["win30"]["pick"] in ("spy", "logit", S.BLEND)
    Spy.seen = []
    S.run(None, None, now, tmp_path, log=lambda *_: None)
    assert Spy.seen == []                             # every day already tested
    assert len(list((tmp_path / "oof" / "win30").glob("*.npz"))) == 3
    md = S.markdown(s1)
    assert "win30" in md and "\u2014" not in md


# ---------------------------------------------------------------- the allocator

def test_rewards_and_days():
    tr = {"P_pool0_wait": [(T0 + 1000, 0.5), (T0 + 2000, -1.0)], "P_pool0_wait_lock": []}
    rw = A.day_rewards(tr, ["2026-10-20", "2026-10-21"])
    assert np.isclose(rw["P_pool0_wait"]["2026-10-20"], np.log(1.05) + np.log(0.9))
    assert rw["P_pool0_wait"]["2026-10-21"] == 0.0 and rw["P_pool0_wait_lock"]["2026-10-20"] == 0.0
    assert A.full_days(T0 + 5, T0 + 3 * DAY + 5) == ["2026-10-21", "2026-10-22"]
    assert A.full_days(T0, T0 + 2 * DAY) == ["2026-10-20", "2026-10-21"]


def rewards(days, means, seed=6):
    rng = np.random.default_rng(seed)
    return {a: {d: float(m + rng.normal(0, 0.02)) for d in days} for a, m in means.items()}


def test_decide_prefers_the_better_arm_with_a_floor():
    days = [f"2026-10-{d:02d}" for d in range(1, 21)]
    rw = rewards(days, {"a": 0.05, "b": 0.0, "c": -0.01})
    res = A.decide(rw, days, "2026-10-21")
    arms = res["arms"]
    assert arms["a"]["p_best"] > 0.9 and res["choice"] in ("a", "b", "c")
    assert all(v["weight"] >= A.FLOOR - 1e-12 for v in arms.values())
    assert abs(sum(v["weight"] for v in arms.values()) - 1) < 1e-9
    assert A.decide(rw, days, "2026-10-21")["choice"] == res["choice"]       # seeded by the day


def test_drawdown_guard():
    days = [f"2026-10-{d:02d}" for d in range(1, 11)]
    rw = rewards(days, {"a": 0.0, "b": 0.0})
    rw["a"]["2026-10-10"] = -0.5                    # 39 % under its peak
    res = A.decide(rw, days, "2026-10-11")
    assert res["arms"]["a"]["guarded"] and res["arms"]["a"]["weight"] == 0.0
    assert res["choice"] == "b" and abs(res["arms"]["b"]["weight"] - 1) < 1e-9
    rw["b"]["2026-10-10"] = -0.5
    res = A.decide(rw, days, "2026-10-11")
    assert res["choice"] is None and "stay out" in A.why(res, "P_pool0_wait")
    assert A.drawdown([0.1, -0.1]) == pytest.approx(1 - 1 / np.exp(0.1))


def test_prior_only_is_uniform():
    res = A.decide({"a": {}, "b": {}, "c": {}}, [], "2026-10-21")
    assert all(abs(v["p_best"] - 1 / 3) < 0.03 for v in res["arms"].values())


def test_allocator_run_reports_and_never_steers(tmp_path, monkeypatch):
    from lab.pumpfun_rt import realistic as R
    paper = tmp_path / "paper"
    paper.mkdir()
    since = T0 + 3_600_000
    (paper / "state.json").write_text(json.dumps({"realistic_since": since}))
    rows = ["rule,exit_ms,ret,pnl_sol",
            f"P_pool0_wait,{T0 + DAY + 10},0.2,0.01", f"P_pool5_top30t,{T0 + DAY + 20},-0.1,-0.005",
            f"P_pool0_wait_ideal,{T0 + DAY + 30},5.0,0.5", f"P_pool0_wait,{T0 + 10},9.0,0.9"]
    (paper / "ledger.csv").write_text("\n".join(rows) + "\n")
    (paper / "failed.csv").write_text(f"rule,mint,signal_ms,land_ms,why,pnl_sol\n"
                                      f"P_pool0_wait_lock,m,{T0 + DAY},{T0 + DAY + 5},x,-0.00022\n")
    out = tmp_path / "rep"
    out.mkdir()
    (out / "live_status.json").write_text(json.dumps({"rule": "P_pool0_wait", "on": False}))
    monkeypatch.setattr(R, "reports_dir", lambda: out)
    before = {p.name: p.read_bytes() for p in paper.iterdir()}
    doc = A.run(T0 + 2 * DAY + 5, paper=paper, out=out, log=lambda *_: None)
    assert {p.name: p.read_bytes() for p in paper.iterdir()} == before
    assert doc["armed"] is False and doc["live_rule"] == "P_pool0_wait"
    got = json.loads((out / "allocator.json").read_text())
    assert set(got["arms"]) == set(A.ARMS) and got["choice"] in A.ARMS
    r = got["arms"]["P_pool0_wait"]["rewards"]
    assert list(r) == ["2026-10-21"] and np.isclose(r["2026-10-21"], np.log(1.02))
    assert np.isclose(got["arms"]["P_pool0_wait_lock"]["rewards"]["2026-10-21"], np.log(1 - 0.1 * 0.004))
    assert "live bot keeps the owner's P_pool0_wait" in got["why"]
    assert "Would pick" in (out / "allocator.md").read_text()


def test_card_line():
    from lab.pumpfun_rt import card
    alloc = {"choice": "P_pool5_top30t", "live_rule": "P_pool0_wait",
             "arms": {"P_pool5_top30t": {"p_best": 0.61, "days": 3}}}
    en = card.daily_card({}, None, {}, None, T0, "en", alloc=alloc).render("telegram", "en")
    de = card.daily_card({}, None, {}, None, T0, "de", alloc=alloc).render("telegram", "de")
    assert "would pick P_pool5_top30t" in en and "live bot keeps P_pool0_wait" in en
    assert "würde P_pool5_top30t nehmen" in de and "Live-Bot behält P_pool0_wait" in de
    out = dict(alloc, choice=None)
    assert "drawdown guard" in card.daily_card({}, None, {}, None, T0, "en", alloc=out).render("telegram", "en")
    assert "Allocator" not in card.daily_card({}, None, {}, None, T0, "en").render("telegram", "en")


# ---------------------------------------------------------------- the study

def test_alloc_test_needs_ten_days():
    days = [f"2026-10-{d:02d}" for d in range(1, 6)]
    rw = rewards(days, {"P_pool0_wait": 0.05, "P_pool0_wait_lock": 0.0, "P_pool5_top30t": -0.02})
    res = AA.alloc_test(rw, days)
    assert len(res["per_day"]) == 5 and not res["enough_days"] and res["verdict"] is False
    assert res["best"] == "P_pool0_wait" and all("p" in c for c in res["comparisons"])
    days = [f"2026-10-{d:02d}" for d in range(1, 31)]
    rw = rewards(days, {"P_pool0_wait": 0.05, "P_pool0_wait_lock": -0.05, "P_pool5_top30t": -0.05})
    res = AA.alloc_test(rw, days)
    assert res["enough_days"] and res["best"] == "P_pool0_wait"
    assert res["per_day"][0]["pick"] in A.ARMS


def test_deflate_and_hourly():
    rows = [dict(AA.sharpe(np.random.default_rng(i).normal(0.1 * i, 1, 200))) for i in range(4)]
    AA.deflate(rows)
    assert all(0 <= r["dsr"] <= 1 and abs(r["p"] + r["dsr"] - 1) < 1e-12 for r in rows)
    assert rows[3]["dsr"] > rows[0]["dsr"]
    t = T0 + np.array([0, 1, 3_600_000, 3_600_001.0])
    assert list(AA.hourly(np.array([1.0, 3, 5, 7]), t)) == [2.0, 6.0]


def test_model_test_on_synthetic_rows(monkeypatch):
    monkeypatch.setattr(S, "LABELS", {"win30": "decision"})
    tab = table(days=4, per_day=700)
    monkeypatch.setattr(S, "table_for", lambda label, rows, sel: tab)
    monkeypatch.setattr(Z, "members_for", lambda kind, names=None: ["logit", "online"])
    res = AA.model_test(None, None, until="2026-10-24", log=lambda *_: None)
    v = res["labels"]["win30"]
    assert v["test_days"] == ["2026-10-21", "2026-10-22", "2026-10-23"]
    assert v["scored_days"] == ["2026-10-22", "2026-10-23"]
    assert v["best"] in ("logit", "online") and res["trials"] == 2
    picks = list(v["picks"].values())                 # lgb first, then (lgb not in the zoo here) the lowest loss
    assert picks[0] == "lgb" and set(picks[1:]) <= {"logit", "online", S.BLEND}
    assert isinstance(res["verdict"], bool)
    md = AA.markdown({"run": "2026-10-26", "models": res, "alloc": None, "rewards": {}, "forward": {}})
    assert "Test 1" in md and "\u2014" not in md
