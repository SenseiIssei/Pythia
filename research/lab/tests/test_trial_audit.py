"""The trial register audit (results/trial_audit_prereg.md): every pre-registered study has a declared count whose
quote is in its file; R5's lines matched by the study's file and the seed groups; the missing counted-only blocks,
T11's stored Sharpes under its own ids, appended once through metrics.register.

Run from research/lab:  python -m pytest tests/test_trial_audit.py
"""

from __future__ import annotations

import json

import pytest

from lab import metrics
from lab.ops import trial_audit as T


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    p = tmp_path / "trials" / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(p))
    return p


def test_every_preregistered_study_is_declared_and_quoted():
    a = T.audit(rows=[])
    assert a["undeclared"] == []
    assert {r["study"] for r in a["rows"]} == set(T.studies())
    bad = [(r["study"], r["file"]) for r in a["rows"] if not r["quote_ok"]]
    assert bad == []
    for s, fam, n, f, q, seed in T.DECLARED:
        assert fam in ("hand", "factory", "small", "pumpfun") and n >= 0 and 20 <= len(q) and "\n" not in q
        assert not seed.startswith("study:") or seed[6:] in {d[0] for d in T.DECLARED}


def test_a_quote_gone_fails_the_row(tmp_path):
    (tmp_path / "x_prereg.md").write_text("# x\n12 trials in R5's registry\n", encoding="utf-8")
    d = [("x", "hand", 12, "x_prereg.md", "12 trials in R5's registry", "")]
    assert T.audit(rows=[], results=tmp_path, declared=d)["rows"][0]["missing"] == 12
    d = [("x", "hand", 12, "x_prereg.md", "13 trials in R5's registry", "")]
    r = T.audit(rows=[], results=tmp_path, declared=d)["rows"][0]
    assert not r["quote_ok"] and r["missing"] is None and "(quote gone)" in "\n".join(
        T.table(T.audit(rows=[], results=tmp_path, declared=d)))


def test_registered_by_the_studys_file_family_and_seed_group(tmp_path):
    for f in ("a_prereg.md", "b_prereg.md", "c_prereg.md", "d_prereg.md"):
        (tmp_path / f).write_text("# x\nfour trials here\n", encoding="utf-8")
    d = [("a", "hand", 4, "a_prereg.md", "four trials here", ""),
         ("a", "small", 2, "a_prereg.md", "four trials here", ""),
         ("b", "hand", 3, "b_prereg.md", "four trials here", "hand:batches_2026_10_21"),
         ("c", "hand", 2, "c_prereg.md", "four trials here", "study:a"),
         ("d", "hand", 0, "d_prereg.md", "four trials here", "")]
    rows = [{"id": "hand:a:1", "family": "hand", "n": 3, "source": "results/a_prereg.md"},
            {"id": "small:a:1", "family": "small", "n": 1, "source": "research/lab/results/a.md (run)"},
            {"id": "hand:other", "family": "hand", "n": 9, "source": "results/ab_prereg.md"},
            {"id": "hand:d", "family": "hand", "n": 2, "source": "results/d.md"}] + metrics.TRIAL_SEED
    a = T.audit(rows=rows, results=tmp_path, declared=d)
    by = {(r["study"], r["family"]): r for r in a["rows"]}
    assert (by["a", "hand"]["registered"], by["a", "hand"]["missing"]) == (3, 1)
    assert (by["a", "small"]["registered"], by["a", "small"]["missing"]) == (1, 1)
    assert by["b", "hand"]["registered"] is None and by["c", "hand"]["group"] == "a"
    assert (by["d", "hand"]["registered"], by["d", "hand"]["missing"]) == (2, 0)          # above declared: shown
    g = a["groups"][0]
    assert g["group"] == "hand:batches_2026_10_21" and (g["declared"], g["registered"], g["missing"]) == (3, 188, 0)
    # the seed block names perps_neutral_portfolio_prereg.md: it counts only through its group
    assert T.held(rows, "perps_neutral_portfolio", "hand") == 0
    add = T.missing_rows(a)
    assert sorted((r["id"], r["n"]) for r in add) == [("audit:a:hand", 1), ("audit:a:small", 1)]
    assert all(r["sharpe"] is None and r["var"] is None for r in add)


def test_missing_blocks_append_once_and_then_count_as_registered(tmp_path, reg):
    (tmp_path / "a_prereg.md").write_text("# x\nfive trials here\n", encoding="utf-8")
    d = [("a", "pumpfun", 5, "a_prereg.md", "five trials here", "")]
    a = T.audit(rows=metrics.read_registry(), results=tmp_path, declared=d)
    assert metrics.register(T.missing_rows(a))[0]["n"] == 5
    a = T.audit(rows=metrics.read_registry(), results=tmp_path, declared=d)
    assert a["rows"][0]["registered"] == 5 and T.missing_rows(a) == []
    assert metrics.register(T.missing_rows(T.audit(rows=metrics.read_registry(), results=tmp_path,
                                                   declared=d + d))) == []
    assert metrics.trial_pool("pumpfun")["n_trials"] == 5


def test_a_stored_series_is_used_under_the_studys_ids(tmp_path):
    (tmp_path / "hl_funding_t11.md").write_text("# x\n5 trials in R5's registry\n", encoding="utf-8")
    d = [("hl_funding_t11", "hand", 5, "hl_funding_t11.md", "5 trials in R5's registry", "")]
    add = T.missing_rows(T.audit(rows=[], results=tmp_path, declared=d))
    assert [r["id"] for r in add] == [i for i, _ in T.SERIES["hl_funding_t11"]]
    assert [r["sharpe"] for r in add] == [2.86, 6.55, 4.65, 7.34, None]
    # registered under those ids, the study counts them as its own
    rows = [{**r, "added": "x"} for r in add]
    assert T.held(rows, "hl_funding_t11", "hand") == 5


def test_main_registers_the_rechecks_and_the_missing_once(reg, capsys):
    T.main(["--register"])
    have = [json.loads(x)["id"] for x in reg.read_text(encoding="utf-8").splitlines()]
    assert "audit:recheck:P_pool0" in have and "audit:recheck:genome" in have
    assert "audit:trial_audit:pumpfun" not in have                       # the rechecks are its two trials
    n = len(have)
    T.main(["--register"])
    assert len(reg.read_text(encoding="utf-8").splitlines()) == n
    assert "missing: 0 trials" in capsys.readouterr().out.splitlines()[-2]
