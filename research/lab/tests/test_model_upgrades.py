"""X11 model upgrades: M2 v3's scoring, M8u and the trim, the window drift test,
M1's flow helpers, the Claude analyst and the news sentiment. Synthetic data, no
network: every Claude call goes to a fake engine.

Run from research/lab:  python -m pytest tests/test_model_upgrades.py
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.ai import analyst, engine, news
from lab.experiments import m1_flow, m2_v3, m8_trim
from lab.models import core, daily, m8_direction, m8_upper

NOW = int(datetime(2026, 10, 20, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)
DAY_US = 86_400_000_000


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "data" / "reports"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.delenv("PYTHIA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    monkeypatch.setattr(analyst, "market_lines", lambda: ["BTC DVOL 50"])
    monkeypatch.setattr(analyst, "funding7", lambda c: 0.0003 if c == "BTC" else None)
    return tmp_path


class Fake:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, url, body, tok, timeout):
        self.calls.append(body)
        return 200, self.answer


# ---------------------------------------------------------------- M2 v3

def test_rank_v3_ranks_coin_inputs_and_leaves_market_inputs_and_drops_infinities():
    days = np.repeat(np.arange(3) * DAY_US, 25)
    n = len(days)
    rng = np.random.default_rng(0)
    raw = pl.DataFrame({"day": days, "symbol": [f"C{i % 25}USDT" for i in range(n)], "fwd": rng.normal(size=n),
                        "oi_chg7": np.where(np.arange(n) % 5 == 0, np.inf, rng.normal(size=n)),
                        "dvol": np.repeat([0.5, -1.0, 2.0], 25)})
    P = m2_v3.rank_v3(raw, ["oi_chg7", "dvol"])
    assert P["dvol"].to_list()[:3] == [0.5, 0.5, 0.5]           # not ranked
    assert P["oi_chg7"].null_count() == n // 5                     # an infinity is missing, not ranked first
    assert P["oi_chg7"].drop_nulls().max() <= 1.0


def test_the_comparison_needs_t_and_two_better_years():
    d = np.array([int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp() * 1e6) + k * DAY_US
                  for y in (2024, 2025, 2026) for m in (1, 4, 7) for k in range(20)])
    rng = np.random.default_rng(1)
    a = pl.DataFrame({"day": d, "ic": 0.15 + 0.02 * rng.normal(size=len(d))})
    b = pl.DataFrame({"day": d, "ic": 0.12 + 0.02 * rng.normal(size=len(d))})
    c = m2_v3.compare(a, b, m2_v3.JUDGE_FROM)
    assert c["diff"] > 0 and c["t"] > m2_v3.PASS_T and c["years_better"] == 3 and m2_v3.passes(c)
    assert not m2_v3.passes(m2_v3.compare(b, a, m2_v3.JUDGE_FROM))


def test_daily_ic_and_percentiles_are_within_the_day():
    day = np.repeat([0, DAY_US], 30)
    x = np.tile(np.arange(30.0), 2)
    assert np.allclose(m2_v3.pct_in_day(day, x)[:30], np.arange(30) / 29)
    ic = m2_v3.daily_ic(day, x, x * 2, np.ones(60, bool))
    assert ic.height == 2 and np.allclose(ic["ic"].to_numpy(), 1.0)
    assert m2_v3.daily_ic(day, x, x, np.zeros(60, bool)).height == 0


def test_the_shadow_scores_recorded_weeks_only(tmp_path, monkeypatch):
    monkeypatch.setattr(m2_v3, "SHADOW_DIR", tmp_path)
    syms = [f"C{i}USDT" for i in range(30)] + ["BTCUSDT"]
    rec = {"day_us": 7 * DAY_US, "recorded_ms": 1, "groups": ["F"],
           "scores": {s: [float(i), float(-i)] for i, s in enumerate(syms)}}
    (tmp_path / "rankings.jsonl").write_text(json.dumps(rec) + "\n")
    realised = pl.DataFrame({"day": [7 * DAY_US] * len(syms), "symbol": syms, "fwd": [float(i) for i in range(len(syms))]})
    out = m2_v3.shadow_score(realised)
    assert out["scored"] == 1 and out["weeks"][0]["ic_v2"] == pytest.approx(1.0)
    assert out["weeks"][0]["ic_v3"] == pytest.approx(-1.0) and out["verdict"].startswith("Too early")
    assert m2_v3.shadow_score(realised.with_columns(day=pl.lit(0)))["scored"] == 0


def test_alpaca_mask_uses_current_tickers_only():
    m = m2_v3.alpaca_mask(np.array(["BTCUSDT", "BTCUSDT~0", "MATICUSDT", "POLUSDT"]))
    assert m.tolist() == [True, False, False, True]


# ---------------------------------------------------------------- M8u

def _m8_panel():
    frames = daily.synthetic_daily(n_days=900)
    return m8_direction.panel_from(daily.enrich(frames)).with_columns(target=pl.col("ret_next"))


def test_m8u_forecasts_the_upper_tail_and_its_ratio():
    p = _m8_panel()
    known = p.filter(pl.col("target").is_not_null())
    fit = m8_upper.fit(known)
    q = m8_upper.predict(fit, known)
    b = m8_upper.baseline(fit, known)
    assert q.shape == (known.height,) and np.all(b > 0)
    cover = float(np.mean(known["target"].to_numpy() <= q))
    assert 0.8 < cover < 0.97
    r = m8_upper.side(fit, known)["ratio"]
    assert np.allclose(r * fit["base_q"] * known["sigma"].to_numpy(), q)
    y = known["target"].to_numpy()
    assert m8_upper.loss(y, q).mean() > 0


def test_m8u_saves_and_restores(tmp_path):
    p = _m8_panel().filter(pl.col("target").is_not_null())
    fit = m8_upper.fit(p)
    m8_upper.save(fit, tmp_path)
    back = m8_upper.restore(tmp_path)
    assert np.allclose(m8_upper.predict(back, p), m8_upper.predict(fit, p))


def test_trim_cut_and_rules():
    T, N = 400, 3
    rng = np.random.default_rng(2)
    U = rng.normal(1.0, 0.1, (T, N))
    U[:, 2] = np.nan                              # no forecast: never trimmed
    ret7 = np.where(np.arange(T)[:, None] % 2 == 0, 0.05, -0.05) * np.ones((T, N))
    cut = m8_trim.trailing_cut(U)
    assert np.isnan(cut[:m8_trim.WINDOW_MIN - 1]).all() and np.isfinite(cut[-1])
    S = m8_trim.trim_scale(U, ret7, "exhaust")
    assert set(np.unique(S)) <= {0.5, 1.0} and (S[:, 2] == 1).all()
    share = (S[200:, :2] < 1).mean()
    assert 0.1 < share < 0.3
    tp = m8_trim.trim_scale(U, ret7, "take-profit")
    assert ((tp < 1) <= (S < 1)).all() and (tp[1::2] == 1).all()   # only after an up week
    late = m8_trim.trim_scale(U, ret7, "exhaust", late=1)
    assert np.array_equal(late[1:], S[:-1]) and (late[0] == 1).all()
    W = np.array([[0.5, np.nan, 0.2]])
    assert np.allclose(m8_trim.trimmed(W, np.array([[0.5, 0.5, 1.0]])), [[0.25, np.nan, 0.2]], equal_nan=True)


def test_a_held_position_is_trimmed_when_the_signal_starts_and_restored_when_it_ends():
    W = np.array([[0.1], [np.nan], [np.nan], [np.nan], [0.0]])          # breakout: enter, hold, exit
    held = np.array([[0.1], [0.11], [0.12], [0.1], [0.0]])
    S = np.array([[1.0], [0.5], [0.5], [1.0], [1.0]])
    out = m8_trim.trimmed(W, S, held)
    assert np.allclose(out[:, 0], [0.1, 0.055, np.nan, 0.1, 0.0], equal_nan=True)
    assert np.allclose(m8_trim.trimmed(W, np.ones_like(S), held), W, equal_nan=True)


# ---------------------------------------------------------------- drift, form W

def _windows(n=120, feats=("a", "b"), seed=3, shift=0.0):
    rng = np.random.default_rng(seed)
    train = rng.normal(size=5000)
    bins = {f: core.drift_bins(train) for f in feats}
    out = []
    for i in range(n):
        checks = {f: core.drift_check(bins[f], rng.normal(loc=shift + 0.3 * np.sin(i / 7), size=300)) for f in feats}
        out.append({"from": i, "to": i + 1, "checks": checks})
    return bins, out


def test_window_calibration_holds_its_false_alarm_rate():
    bins, w = _windows()
    cal = core.drift_calibration_window(bins, w, 30)
    assert cal["mode"] == "window_max" and cal["false_alarm_train"] <= 0.05
    rate = np.mean([core.calibrated_level(x["checks"], cal)[0] != "stable" for x in w])
    assert rate <= 0.05


def test_window_calibration_flags_a_real_shift_and_names_drift():
    bins, w = _windows()
    cal = core.drift_calibration_window(bins, w, 30)
    _, moved = _windows(n=10, seed=4, shift=2.0)
    levels = [core.calibrated_level(x["checks"], cal)[0] for x in moved]
    assert all(lv != "stable" for lv in levels) and "drift" in levels
    assert core.drift_calibration_window(bins, w[:5], 30) is None


def test_old_calibrations_keep_their_rule():
    checks = {"a": {"psi": 0.3, "outside_pct": 1.0, "level": "shift"}}
    cal = {"k": 1, "cuts": {"a": {"psi": 0.25, "outside": 2.0}}}
    assert core.calibrated_level(checks, cal) == ("shift", 1)


# ---------------------------------------------------------------- M1 flow

def test_flow_inputs_lose_their_infinities():
    p = pl.DataFrame({"oi_chg1h": [1.0, math.inf, -math.inf, float("nan")], "x": [math.inf] * 4})
    q = m1_flow.finite_only(p, ["oi_chg1h"])
    assert q["oi_chg1h"].to_list() == [1.0, None, None, None] and q["x"].to_list()[0] == math.inf


def test_ols_recovers_a_line():
    X = np.arange(20.0)[:, None]
    assert np.allclose(m1_flow.ols(X, 1 + 2 * X[:, 0]), [1, 2])


# ---------------------------------------------------------------- Claude analyst

def bars(n=400, last="2026-10-19", drift=0.001, vol=0.03, seed=0):
    rng = np.random.default_rng(seed)
    d0 = date.fromisoformat(last) - timedelta(days=n - 1)
    c = 100 * np.exp(np.cumsum(drift + vol * rng.normal(size=n)))
    return [{"day": (d0 + timedelta(days=i)).isoformat(), "close": float(c[i]), "high": float(c[i] * 1.01),
             "qv": float(1e6 * (1 + i / n))} for i in range(n)]


COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"]


def analyst_text(cs, ranks=None, drop=(), fence=False):
    """A local model's answer: every coin of `cs` (minus `drop`) with its rank (by default 1..n in order)."""
    ranks = ranks or list(range(1, len(cs) + 1))
    t = json.dumps({"ranking": [{"coin": c, "expectedRank": r, "pUp7d": 0.52, "reason": f"{c} \u2014 calm"}
                                for c, r in zip(cs, ranks) if c not in drop], "market": "flat"})
    return f"```json\n{t}\n```" if fence else t


class FakeChat:
    """lab.ai.local.chat with a fake backend: the answers in turn (a text, or None: no backend answered)."""

    def __init__(self, *answers, backend="vps"):
        self.answers = list(answers)
        self.backend = backend
        self.calls = []

    def __call__(self, messages, use, max_tokens=160, deadline=None, timeout=45.0, env=None, bks=None):
        self.calls.append({"messages": messages, "use": use, "max_tokens": max_tokens, "bks": bks})
        a = self.answers.pop(0) if self.answers else None
        return None if a is None else {"text": a, "backend": self.backend, "tokens": 900, "seconds": 240.0}


EM = "\u2014"  # the em dash, which the lab never writes
VPS_ENV = {"PYTHIA_LOCAL_LLM_URL": "http://127.0.0.1:9"}


def run_analyst(lab, monkeypatch, chat, now=NOW, env=None):
    monkeypatch.setattr(analyst, "coins", lambda: COINS)
    data = {c: bars(seed=i) for i, c in enumerate(COINS)}
    return analyst.run(now, loader=lambda c: data[c], chat=chat, env=VPS_ENV if env is None else env)


def skips(lab):
    p = lab / "data" / "ai" / "analyst_skips.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_the_strict_parser_names_the_first_problem_and_repairs_nothing():
    cs = ["BTC", "ETH", "SOL"]
    got, why = analyst.parse_strict(analyst_text(cs, fence=True), cs)
    assert why == "" and [got[c]["rank"] for c in cs] == [1, 2, 3] and EM not in got["BTC"]["reason"]
    assert analyst.parse_strict(analyst_text(cs, drop=("SOL",)), cs) == (None, "no entry for SOL")
    assert analyst.parse_strict(analyst_text(cs, ranks=[1, 1, 2]), cs)[1] == "rank 1 is given twice (BTC and ETH)"
    assert analyst.parse_strict(analyst_text(cs, ranks=[1, 2, 4]), cs)[1].startswith("SOL: expectedRank 4")
    assert analyst.parse_strict(analyst_text(cs, ranks=[1, 2, 2.5]), cs)[0] is None
    assert analyst.parse_strict(analyst_text(cs + ["XYZ"]), cs)[1] == "XYZ was not asked for"
    twice = json.loads(analyst_text(cs))
    twice["ranking"].append(dict(twice["ranking"][0]))
    assert analyst.parse_strict(json.dumps(twice), cs)[1] == "BTC is listed twice"
    bad_p = json.loads(analyst_text(cs))
    bad_p["ranking"][1]["pUp7d"] = 1.4
    assert analyst.parse_strict(json.dumps(bad_p), cs)[1].startswith("ETH: pUp7d 1.4")
    assert analyst.parse_strict('{"ranking": [', cs)[1].startswith("not valid JSON")
    assert analyst.parse_strict("Here is my ranking: BTC first", cs)[0] is None
    assert analyst.parse_strict('{"market": "x"}', cs)[1] == 'no "ranking" list in the JSON object'


def test_the_fact_sheet_reads_the_past_only():
    b = bars()
    f = analyst.features(b)
    assert f["ref_day"] == "2026-10-19" and f["ref_close"] == b[-1]["close"]
    assert math.isclose(f["r7"], b[-1]["close"] / b[-8]["close"] - 1)
    assert analyst.features(b[:50]) is None


def test_the_prompt_fits_the_vps_models_context_with_its_answer():
    from lab import universe
    cs = list(universe.ALPACA)
    feats = {c: analyst.features(bars(seed=i)) for i, c in enumerate(cs)}
    feats[cs[0]] = {**feats[cs[0]], "ref_day": "2026-10-18"}
    p = analyst.build_prompt("2026-10-20", feats, {c: 0.0003 for c in cs}, ["BTC DVOL 50"])
    assert f"{cs[1]} | " in p and "| reference 2026-10-18" in p and p.count("reference 2026-10-") == 1
    assert analyst.est_tokens(analyst.SYSTEM + p) + analyst.max_out(len(cs)) < analyst.VPS_CONTEXT
    assert EM not in analyst.SYSTEM + p


def test_a_good_answer_is_recorded_with_its_backend_and_model_and_one_trial(lab, monkeypatch):
    chat = FakeChat(analyst_text(COINS))
    assert run_analyst(lab, monkeypatch, chat) == 0
    assert len(chat.calls) == 1 and chat.calls[0]["use"] == "analyst"
    assert chat.calls[0]["max_tokens"] == analyst.max_out(len(COINS)) and chat.calls[0]["bks"][0]["name"] == "vps"
    rows = analyst.read_rows()
    assert len(rows) == len(COINS) and [r["rank"] for r in rows] == list(range(1, 7))
    assert {(r["backend"], r["model"]) for r in rows} == {("vps", "qwen3-4b-instruct")}
    assert all(EM not in r["reason"] for r in rows)
    ids = [r["id"] for r in metrics.read_registry()]
    assert "hand:t15:analyst_e1b_vps_qwen3-4b-instruct" in ids and skips(lab) == []
    rep = json.loads((lab / "data" / "reports" / analyst.NAME / "latest.json").read_text())
    assert rep["last_model"] == "qwen3-4b-instruct" and rep["last_backend"] == "vps" and rep["scored"] == 0
    assert rep["current_series"] == "vps:qwen3-4b-instruct" and "qwen3-4b-instruct (vps)" in rep["headline"]
    # Not due again the next day.
    assert run_analyst(lab, monkeypatch, chat, NOW + 86_400_000) == 0 and len(chat.calls) == 1


def test_a_missing_coin_twice_skips_the_week_and_fills_nothing(lab, monkeypatch):
    chat = FakeChat(analyst_text(COINS, drop=("SOL",)), analyst_text(COINS, drop=("SOL",)))
    assert run_analyst(lab, monkeypatch, chat) == 1
    assert len(chat.calls) == 2 and "no entry for SOL" in chat.calls[1]["messages"][1]["content"]
    assert chat.calls[1]["bks"][0]["name"] == "vps", "the retry asks the same backend"
    assert analyst.read_rows() == []
    sk = skips(lab)
    assert len(sk) == 1 and sk[0]["backend"] == "vps" and "on the retry no entry for SOL" in sk[0]["why"]
    assert not [r for r in metrics.read_registry() if r["id"].startswith(analyst.TRIAL_PREFIX)]
    # The week stays skipped: no call the next day.
    assert run_analyst(lab, monkeypatch, FakeChat(analyst_text(COINS)), NOW + 86_400_000) == 0
    assert analyst.read_rows() == []


def test_a_duplicate_rank_is_asked_again_with_the_problem_named(lab, monkeypatch):
    chat = FakeChat(analyst_text(COINS, ranks=[1, 1, 2, 3, 4, 5]), analyst_text(COINS))
    assert run_analyst(lab, monkeypatch, chat) == 0
    retry = chat.calls[1]
    assert retry["use"] == "analyst:retry" and "rank 1 is given twice (BTC and ETH)" in retry["messages"][1]["content"]
    assert retry["messages"][0]["content"] == analyst.SYSTEM and len(retry["messages"]) == 2
    assert [r["rank"] for r in analyst.read_rows()] == list(range(1, 7)) and skips(lab) == []


def test_broken_json_then_a_good_retry_is_recorded(lab, monkeypatch):
    chat = FakeChat('{"ranking": [{"coin": "BTC", "expectedRank": 1,', analyst_text(COINS, fence=True))
    assert run_analyst(lab, monkeypatch, chat) == 0
    assert "not valid JSON" in chat.calls[1]["messages"][1]["content"]
    assert len(analyst.read_rows()) == len(COINS)


def test_no_backend_answering_is_a_red_job_and_a_skipped_week(lab, monkeypatch):
    chat = FakeChat(None)
    assert run_analyst(lab, monkeypatch, chat) == 1
    assert len(chat.calls) == 1 and analyst.read_rows() == []
    assert skips(lab)[0]["why"] == "no backend answered" and skips(lab)[0]["backend"] is None
    bad_then_none = FakeChat(analyst_text(COINS, ranks=[2] * 6), None)
    assert run_analyst(lab, monkeypatch, bad_then_none, NOW + 9 * 86_400_000) == 1, "a bad answer, no answer on the retry"
    assert "no answer on the retry" in skips(lab)[1]["why"] and analyst.read_rows() == []
    rep = json.loads((lab / "data" / "reports" / analyst.NAME / "latest.json").read_text())
    assert rep["last_skip"]["why"] == skips(lab)[1]["why"]
    # The model switched off: nothing is asked, the week is skipped.
    off = FakeChat(analyst_text(COINS))
    assert run_analyst(lab, monkeypatch, off, NOW + 20 * 86_400_000, env={"PYTHIA_LOCAL_LLM": "off"}) == 1
    assert off.calls == [] and "off" in skips(lab)[2]["why"]


def test_each_backend_and_model_is_its_own_series_and_claude_stays_apart(lab, monkeypatch):
    claude = [{"date": "2026-10-01", "made_ms": NOW - 30 * 86_400_000, "coin": c, "ref_day": "2026-09-30",
               "ref_close": 100.0, "rank": i + 1, "p_up": 0.5, "p_base": 0.5, "vol30": 0.5, "r28": 0.0,
               "model": "claude-sonnet-5-5", "cost_usd_call": 0.02} for i, c in enumerate(COINS)]
    from lab.ai import score
    score.append_predictions(claude, analyst.path())
    env = {**VPS_ENV, "PYTHIA_LOCAL_LLM_RELAY_URL": "http://127.0.0.1:9", "PYTHIA_LOCAL_LLM_TOKEN": "t",
           "PYTHIA_LOCAL_LLM_RELAY_MODEL": "big-model"}
    monkeypatch.setattr(analyst.local, "relay_online", lambda e=None: (bool((e or {}).get("PYTHIA_LOCAL_LLM_RELAY_URL")), ""))
    assert run_analyst(lab, monkeypatch, FakeChat(analyst_text(COINS), backend="relay"), env=env) == 0
    assert run_analyst(lab, monkeypatch, FakeChat(analyst_text(COINS)), NOW + 9 * 86_400_000) == 0
    rows = analyst.read_rows()
    assert {analyst.series(r) for r in rows} == {"claude", "relay:big-model", "vps:qwen3-4b-instruct"}
    rep = json.loads((lab / "data" / "reports" / analyst.NAME / "latest.json").read_text())
    assert set(rep["series"]) == {"claude", "relay:big-model", "vps:qwen3-4b-instruct"}
    assert all(s["recorded_weeks"] == 1 for s in rep["series"].values()) and rep["current_series"] == "vps:qwen3-4b-instruct"
    assert rep["cost_usd_total"] == pytest.approx(0.02)
    ids = {r["id"] for r in metrics.read_registry() if r["id"].startswith(analyst.TRIAL_PREFIX)}
    assert ids == {"hand:t15:analyst_e1b_relay_big-model", "hand:t15:analyst_e1b_vps_qwen3-4b-instruct"}


def test_the_dry_run_prints_the_prompt_size_and_asks_nothing(lab, monkeypatch, capsys):
    monkeypatch.setattr(analyst, "coins", lambda: COINS)
    data = {c: bars(seed=i) for i, c in enumerate(COINS)}
    chat = FakeChat(analyst_text(COINS))
    assert analyst.run(NOW, dry_run=True, loader=lambda c: data[c], chat=chat, env=VPS_ENV) == 0
    out = capsys.readouterr().out
    assert chat.calls == [] and "[dry run]" in out and "input tokens" in out and "context is 4,096" in out
    assert analyst.read_rows() == [] and skips(lab) == []


def test_the_analyst_job_runs_on_the_local_chain():
    from lab.ops import jobs
    j = jobs.load_table(Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml").jobs["ai-analyst"]
    assert "/etc/pythia/local-llm.env?" in j["env_file"] and j["network"] == "host"
    assert not j.get("lock") and j["command"] == "python -m lab.ai.analyst" and j["depends_on"] == ["paper-ls-v2"]
    assert j["timeout"] in ("60m", 3600) and "Claude" not in j["description"]


def test_the_briefing_names_the_model_that_answered():
    from lab.ops import briefing
    rep = {"last_model": "qwen3-4b-instruct", "last_backend": "vps", "last_ref_day": "2026-10-27",
           "last_made_ms": NOW, "scored": 3, "min_weeks": 26}
    line = briefing.analyst_line(rep, "de")
    assert line.text == "qwen3-4b-instruct (VPS) hat für 2026-10-27 geantwortet, 3 von 26 Wochen bewertet"
    assert "big-model (PC)" in briefing.analyst_line({**rep, "last_model": "big-model", "last_backend": "relay"}, "en").text
    skipped = {**rep, "last_skip": {"made_ms": NOW + 1, "ref_day": "2026-11-03", "backend": "vps", "why": "no entry for SOL"}}
    assert briefing.analyst_line(skipped, "en").text == "2026-11-03 skipped (VPS): no entry for SOL"
    assert briefing.analyst_line(None, "en") is None and briefing.analyst_line({"scored": 0}, "en") is None
    lines = briefing.lab_section(None, NOW, "en", root=Path("/nonexistent"), analyst=rep)
    assert [x.text for x in lines] == ["qwen3-4b-instruct (VPS) answered for 2026-10-27, 3 of 26 weeks scored"]


def test_analyst_weeks_are_scored_like_m2():
    rows = [{"coin": c, "ref_day": "2026-10-01", "ref_close": 100.0, "rank": i + 1, "p_up": 0.6, "p_base": 0.5,
             "vol30": 0.5 + i, "r28": 0.0} for i, c in enumerate(COINS)]
    # Realised: the analyst's order exactly; low vol the same order too.
    data = {c: [{"day": "2026-10-01", "close": 100.0}, {"day": "2026-10-08", "close": 110.0 - 3 * i}]
            for i, c in enumerate(COINS)}
    m2 = {"2026-10-01": {c: 1 - i / 10 for i, c in enumerate(COINS)}}
    s = analyst.score_rows(rows, data, m2)
    w = s["weeks"][0]
    assert w["ic_analyst"] == pytest.approx(1.0) and w["ic_lowvol"] == pytest.approx(1.0) and w["ic_m2"] == pytest.approx(1.0)
    assert s["verdict"].startswith("Too early")


def test_the_analyst_waits_for_the_m2_rebalance(lab):
    rows = [{"made_ms": NOW - 7 * 86_400_000}]
    ok, why = analyst.due(NOW, rows, False)
    assert not ok and "rebalance" in why
    assert not analyst.due(NOW, [{"made_ms": NOW - 2 * 86_400_000}], False)[0]
    assert analyst.due(NOW, [{"made_ms": NOW - 9 * 86_400_000}], False)[1] == "no call for a week"
    st = lab / "data" / "paper" / "picks_ls_v2"
    st.mkdir(parents=True)
    (st / "state.json").write_text(json.dumps({"last_rebalance_ms": NOW - 3_600_000}))
    assert analyst.due(NOW, rows, False) == (True, "the M2 v2 book rebalanced today")


# ---------------------------------------------------------------- news

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Bitcoin Cash rallies as BCH miners return</title><pubDate>Sun, 19 Oct 2026 10:00:00 GMT</pubDate><link>https://x/1</link></item>
<item><title>Bitcoin ETF flows turn positive; ETH lags</title><pubDate>Sun, 19 Oct 2026 12:00:00 +0000</pubDate><link>https://x/2</link></item>
<item><title>Trump speaks on tariffs</title><pubDate>Sun, 19 Oct 2026 13:00:00 GMT</pubDate></item>
<item><title>$TRUMP memecoin unlock looms</title><pubDate>Sun, 19 Oct 2026 14:00:00 GMT</pubDate></item>
<item><title>No date here, SOL</title></item>
</channel></rss>"""


def test_feeds_parse_and_headlines_match_coins():
    items = news.parse_feed(RSS, "Test")
    assert len(items) == 4 and items[0]["source"] == "Test"
    m = [news.coins_in(i["title"]) for i in items]
    assert m[0] == ["BCH"]                         # bitcoin cash is not bitcoin
    assert set(m[1]) == {"BTC", "ETH"}
    assert m[2] == [] and m[3] == ["TRUMP"]        # the politician is not the coin
    assert set(news.coins_in("Solana and Polkadot")) == {"DOT", "SOL"}
    assert news.coins_in("a dotted line, solid ground") == []
    assert news.parse_feed(b"not xml", "x") == []


def test_collect_keeps_each_headline_once(lab):
    assert news.collect(fetcher=lambda url: RSS) == 4
    assert news.collect(fetcher=lambda url: RSS) == 0
    rows = news.read_jsonl(news.news_dir() / "2026-10-19.jsonl")
    assert len(rows) == 4


def test_news_scores_yesterday_once_with_one_call(lab):
    news.collect(fetcher=lambda url: RSS)
    ans = {"json": {"scores": [{"coin": "BTC", "sentiment": 0.4, "relevant": 1},
                               {"coin": "TRUMP", "sentiment": -3, "relevant": 1},
                               {"coin": "NOPE", "sentiment": 1, "relevant": 1}]},
           "model": engine.ROUTINE, "costUsd": 0.001, "batchId": "b"}
    fake = Fake(ans)
    assert news.run(NOW, loader=lambda c: [], poster=fake) == 0
    assert len(fake.calls) == 1 and fake.calls[0]["model"] == engine.ROUTINE
    rows = news.read_jsonl(news.sentiment_path())
    by = {r["coin"]: r for r in rows}
    assert set(by) == {"BTC", "TRUMP"} and by["TRUMP"]["sentiment"] == -1.0 and by["BTC"]["day"] == "2026-10-19"
    assert news.run(NOW, loader=lambda c: [], poster=fake) == 0
    assert len(fake.calls) == 1


def test_news_is_tested_against_m2_on_m2_days():
    rows = [{"day": "2026-10-01", "coin": c, "sentiment": s} for c, s in (("BTC", 1.0), ("ETH", -1.0))]
    data = {c: [{"day": "2026-10-01", "close": 100.0}, {"day": "2026-10-08", "close": 100.0 + 5 * (5 - i)}]
            for i, c in enumerate(COINS)}
    m2 = {"2026-10-01": {c: i / 10 for i, c in enumerate(COINS)}}
    s = news.score_rows(rows, data, m2)
    assert s["m2_weeks"] == 1 and s["weeks"][0]["ic_m2"] == pytest.approx(-1.0)
    assert s["verdict"].startswith("Too early")
