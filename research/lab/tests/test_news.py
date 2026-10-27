"""Pythia News (lab.ops.news): one test per source on small fixtures, dedupe and updates, the empty data folder."""

import json
from pathlib import Path

from lab.ops import news

NOW = 1_793_100_000_000            # 2026-10-27 UTC
ADDR = "Wa11et" + "x" * 38            # made up, base58 and as long as a wallet address


def put(root: Path, rel: str, data) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p


def go(root: Path, results: Path | None = None, now: int = NOW, summarize=None) -> dict:
    return news.run(root=root, results=results or (root / "no_results"), now=now, summarize=summarize)


def arts(res: dict, prefix: str = "") -> list[dict]:
    return [a for a in res["doc"]["articles"] if a["id"].startswith(prefix)]


def check_shape(a: dict) -> None:
    assert a["category"] in news.CATEGORIES
    assert 1 <= a["importance"] <= 3
    assert news.MIN_WORDS <= news.words(a["body"]) <= news.MAX_WORDS, (a["id"], news.words(a["body"]))
    assert a["headline"] and a["teaser"] and a["time"] and a["source"]
    assert "\u2014" not in json.dumps(a, ensure_ascii=False)


def test_an_empty_data_folder_writes_an_empty_paper(tmp_path):
    res = go(tmp_path)
    doc = json.loads((tmp_path / "reports/news/articles.json").read_text(encoding="utf-8"))
    assert doc["articles"] == [] and doc["count"] == 0
    assert doc["categories"] == list(news.CATEGORIES)
    assert res["touched"] == []


def test_lanes_done_and_stopped(tmp_path):
    put(tmp_path, "reports/lanes/99-x.json", {"name": "99-x", "title": "Realistisches Papier (R1)", "status": "done",
                                              "at": 1_793_000_000, "commit": "abc1234", "files": ["a.py", "b.py"],
                                              "report": "# R1 Bericht\n\n- Neu: ein Modul. Es rechnet die Kosten mit."})
    put(tmp_path, "reports/lanes/98-y.json", {"name": "98-y", "title": "98-y", "status": "stopped", "at": 1_792_000_000,
                                              "reason": "Datei fehlt: task.md.", "files": []})
    res = go(tmp_path)
    a = {x["id"]: x for x in arts(res, "lane-")}
    assert set(a) == {"lane-99-x", "lane-98-y"}
    done, stopped = a["lane-99-x"], a["lane-98-y"]
    check_shape(done), check_shape(stopped)
    assert done["category"] == "Forschung" and done["headline"].startswith("Erledigt")
    assert done["key"] == {"label": "Dateien geändert", "value": "2"}
    assert done["teaser"].startswith("Neu: ein Modul")             # no markdown marks in the teaser
    assert "### R1 Bericht" in done["body"]                          # the report's heading below the article's
    assert stopped["category"] == "Betrieb" and "task.md" in stopped["body"]
    # Newest first.
    assert [x["id"] for x in res["doc"]["articles"]][:2] == ["lane-99-x", "lane-98-y"]


def test_studies_new_changed_and_first_run(tmp_path):
    res_dir = tmp_path / "results"
    put(res_dir, "y17.md", "# Y17: shapes\n\nIntro.\n\n## The answer\n\nThe CNN ranks the rug label at AUC 0.99; "
                            "the band is 12 %.\n\n## Setup\n\nlong\n")
    put(res_dir, "y18_prereg.md", "# Y18: pre-registration\n\nRegistered first.\n")
    put(res_dir, "review_2026-10-27.md", "# R0 review\n\n## Verdict: five findings\n\n1. **Caps** can be off.\n")
    r1 = go(tmp_path, res_dir)
    a = {x["id"]: x for x in arts(r1, "study-")}
    assert set(a) == {"study-y17", "study-y18_prereg", "study-review_2026-10-27"}
    for x in a.values():
        check_shape(x)
    assert "AUC 0.99" in a["study-y17"]["body"] and a["study-y17"]["key"]["value"] == "12 %"
    assert a["study-y18_prereg"]["headline"].startswith("Vorregistriert") and a["study-y18_prereg"]["importance"] == 1
    assert a["study-review_2026-10-27"]["importance"] == 3
    # Unchanged: nothing new. Changed: the same id, edited and marked updated.
    assert go(tmp_path, res_dir, NOW + 1)["touched"] == []
    put(res_dir, "y17.md", "# Y17: shapes\n\n## The answer\n\nNow AUC 0.95.\n")
    r3 = go(tmp_path, res_dir, NOW + 2)
    assert [x["id"] for x in r3["touched"]] == ["study-y17"]
    y17 = next(x for x in arts(r3, "study-y17"))
    assert y17["updated"] is True and y17["updated_ms"] == NOW + 2 and "AUC 0.95" in y17["body"]
    assert len(arts(r3, "study-")) == 3                              # one event, one article


def test_the_first_run_writes_only_the_newest_studies(tmp_path):
    res_dir = tmp_path / "results"
    for i in range(news.FIRST_STUDIES + 5):
        put(res_dir, f"s{i:02d}.md", f"# S{i}\n\nText {i}.\n")
    assert len(arts(go(tmp_path, res_dir), "study-")) == news.FIRST_STUDIES
    put(res_dir, "s00.md", "# S0\n\nChanged.\n")
    assert [x["id"] for x in go(tmp_path, res_dir, NOW + 1)["touched"]] == ["study-s00"]


def test_factories(tmp_path):
    put(tmp_path, "reports/pumpfun_rt/factory.json", {
        "updated_ms": NOW - 1000, "night": "2026-10-27", "trials_ever": 330, "trials_tonight": 300,
        "bar": {"sharpe": 4.97, "trials": 330}, "best": [{"id": "F3_00296", "pnl_sol": 0.26, "entries": 25}],
        "holdback": [{"id": "F3_00296", "pnl_sol": -0.03, "entries": 40}], "books": [{"book": "F3_00011"}],
        "proposals": []})
    put(tmp_path, "reports/smallaccount/factory.json", {"updated_ms": NOW - 2000, "run_id": "2026-10-27",
                                                        "headline": "Nothing new survives.", "search": {"evaluated": 60},
                                                        "pool_after": {"n_trials": 136}, "shadows": []})
    put(tmp_path, "reports/factory/latest.json", {"updatedMs": NOW - 3000, "run_id": "2026-10-25",
                                                  "headline": "Nothing survives.", "pool_after": {"n_trials": 1277},
                                                  "promoted": [], "shadows": [1]})
    a = {x["id"]: x for x in arts(go(tmp_path), "factory-")}
    assert set(a) == {"factory-F3-2026-10-27", "factory-F2-2026-10-27", "factory-S-2026-10-25"}
    for x in a.values():
        check_shape(x)
        assert x["category"] == "Fabrik"
    f3 = a["factory-F3-2026-10-27"]
    assert "F3_00296" in f3["headline"] and "**300**" in f3["body"] and "-0,030 SOL" in f3["body"]
    assert f3["about"] == ["book:F3_00011", "factory:F3"]


def test_models_zoo_allocator_and_decisions(tmp_path):
    put(tmp_path, "reports/pumpfun_rt/zoo.json", {"updated_ms": NOW, "labels": {"win30": {
        "days": 6, "pick": "blend", "members": ["lgb", "hgb"],
        "changes": [{"day": "2026-10-26", "from": "lgb", "to": "blend", "why": "5 days ahead"}]}}})
    put(tmp_path, "reports/pumpfun_rt/allocator.json", {"updated_ms": NOW, "choice": "P_pool0_wait",
                                                        "live_rule": "P_pool0_wait", "why": "best",
                                                        "arms": {"P_pool0_wait": {"p_best": 0.73, "weight": 0.7, "days": 2}}})
    put(tmp_path, "reports/models/latest.json", {"models": [{"code": "M8", "title": "Direction", "decisions": [
        {"date": "2026-10-20", "decision": "promoted", "challenger_score": 0.6, "champion_score": 0.7, "why": "better"},
        {"date": "2026-10-21", "decision": "kept"}]}]})
    r = go(tmp_path)
    ids = {x["id"] for x in arts(r)}
    assert {"zoo-win30-2026-10-26-blend", "model-M8-2026-10-20-promoted"} <= ids
    assert not any("kept" in i for i in ids)                         # the routine verdict is no news
    alloc = arts(r, "alloc-")
    assert len(alloc) == 1 and alloc[0]["key"]["value"] == "73 %"
    for x in arts(r):
        check_shape(x)
    # The same pick again is no news; a new pick is.
    assert not arts(go(tmp_path, now=NOW + 86_400_000), "alloc-")[1:]
    put(tmp_path, "reports/pumpfun_rt/allocator.json", {"updated_ms": NOW + 2 * 86_400_000, "choice": "P_lock",
                                                        "arms": {"P_lock": {"p_best": 0.5}}})
    r3 = go(tmp_path, now=NOW + 2 * 86_400_000)
    assert [x["id"] for x in r3["touched"] if x["id"].startswith("alloc-")] == ["alloc-2026-10-29-P_lock"]


def book(name, ret, dd, ready=False, dd95=10.0):
    return {"name": name, "label": name.upper(), "days": 22, "return_pct": ret, "max_dd_pct": dd,
            "expected": {"low_pct": -5, "high_pct": 9, "dd_p95_pct": dd95}, "sentence": "Below the range.",
            "gate7": {"days": 22, "days_needed": 30, "trades": 18, "trades_needed": 30, "ready": ready}}


def test_books_bar_high_and_drawdown(tmp_path):
    fw = "reports/forward/latest.json"
    put(tmp_path, fw, {"generated_ms": NOW, "books": [book("tsmom", 2.0, 3.0), book("memes", -9.0, 12.0)]})
    r1 = go(tmp_path)
    ids = [x["id"] for x in r1["touched"]]
    assert ids == ["book-memes-dd-2026-10-27"]                       # the first run: alarms only, no highs
    dd = arts(r1, "book-memes-dd")[0]
    check_shape(dd)
    assert dd["category"] == "Warnung" and dd["about"] == ["book:memes"]
    put(tmp_path, fw, {"generated_ms": NOW + 86_400_000,
                       "books": [book("tsmom", 3.5, 3.0, ready=True), book("memes", -9.5, 12.5)]})
    r2 = go(tmp_path, now=NOW + 86_400_000)
    ids = sorted(x["id"] for x in r2["touched"])
    assert ids == ["book-tsmom-bar", "book-tsmom-high-2026-10-28"]   # the alarm is not repeated
    for x in r2["touched"]:
        check_shape(x)
    assert next(x for x in r2["touched"] if x["id"] == "book-tsmom-bar")["category"] == "Geld"
    r3 = go(tmp_path, now=NOW + 86_400_001)
    assert r3["touched"] == []


def test_money_off_is_news_once_and_never_the_address(tmp_path):
    st = {"t": NOW, "running": False, "on": False, "mode": "test", "rule": "P_pool0_wait", "address": ADDR,
          "balance_sol": 0.04, "pnl_total_sol": -0.4766, "trades_total": 149, "gate": [f"paused by the owner, {ADDR}"]}
    put(tmp_path, "reports/pumpfun_rt/live_status.json", st)
    put(tmp_path, "reports/pumpfun_rt/wallet.json", {"address": ADDR})
    r1 = go(tmp_path)
    a = arts(r1, "live-pumpfun-")
    assert [x["id"] for x in a] == ["live-pumpfun-aus-2026-10-27"]
    check_shape(a[0])
    assert a[0]["key"]["value"] == "-0,477 SOL" and a[0]["importance"] == 3
    assert go(tmp_path, now=NOW + 60_000)["touched"] == []
    put(tmp_path, "reports/pumpfun_rt/live_status.json", {**st, "running": True, "on": True})
    r3 = go(tmp_path, now=NOW + 120_000)
    assert [x["id"] for x in r3["touched"]] == ["live-pumpfun-an-2026-10-27"]
    text = (tmp_path / "reports/news/articles.json").read_text(encoding="utf-8")
    assert ADDR not in text


def test_health_red_and_green_again(tmp_path):
    def jobs(state, fails):
        return {"at": "2026-10-27T13:10:00Z", "jobs": [
            {"name": "pokemon", "enabled": True, "state": state, "consecutiveFailures": fails,
             "description": "cards", "detail": "last run failed, exit 1", "last": {"end": "2026-10-27T13:00:00Z"}},
            {"name": "flow-collect", "enabled": True, "state": "ok", "last": {"end": "2026-10-27T00:41:00Z"}},
            {"name": "off-job", "enabled": False, "state": "disabled"}]}
    put(tmp_path, "_health/jobs.json", jobs("failed", 3))
    put(tmp_path, "_health/status.json", {"at": "2026-10-27T13:10:00Z", "streams": {"kraken": {"stale": False, "messages": 5}}})
    r1 = go(tmp_path)
    assert [x["id"] for x in r1["touched"]] == ["health-pokemon-rot-2026-10-27T13:00"]
    red = r1["touched"][0]
    check_shape(red)
    assert red["category"] == "Warnung" and red["about"] == ["job:pokemon"]
    assert go(tmp_path, now=NOW + 1)["touched"] == []
    j = jobs("ok", 0)
    j["jobs"][0]["last"] = {"end": "2026-10-27T14:00:00Z"}
    put(tmp_path, "_health/jobs.json", j)
    put(tmp_path, "_health/status.json", {"at": "2026-10-27T14:10:00Z", "streams": {"kraken": {"stale": True, "messages": 9}}})
    r2 = go(tmp_path, now=NOW + 2)
    ids = sorted(x["id"] for x in r2["touched"])
    assert ids == ["health-pokemon-gruen-2026-10-27T14:00", "stream-kraken-alt-2026-10-27T14"]
    for x in r2["touched"]:
        check_shape(x)


def test_briefing(tmp_path):
    put(tmp_path, "reports/notify/latest.json", {"ts": NOW, "delivered": True,
                                                 "text": "Guten Morgen\n7 Aufgaben fertig · Autopiloten heute -184,39 $\nmehr"})
    a = arts(go(tmp_path), "briefing-")
    assert [x["id"] for x in a] == ["briefing-2026-10-27"]
    check_shape(a[0])
    assert a[0]["teaser"].startswith("7 Aufgaben fertig") and "job:briefing" in a[0]["about"]


def test_merge_keeps_the_newest_and_caps(tmp_path):
    old = [news.article(f"x-{i}", NOW - i, "Betrieb", f"H{i}", "T.", [("A", "b")]) for i in range(news.MAX_ARTICLES)]
    new = [news.article("x-new", NOW + 5, "Betrieb", "New", "T.", [("A", "b")])]
    out, touched = news.merge(old, new, NOW + 5)
    assert len(out) == news.MAX_ARTICLES and out[0]["id"] == "x-new" and [t["id"] for t in touched] == ["x-new"]
    assert out[-1]["id"] == f"x-{news.MAX_ARTICLES - 2}"


def test_a_broken_source_does_not_stop_the_others(tmp_path):
    put(tmp_path, "reports/forward/latest.json", "{not json")
    put(tmp_path, "reports/notify/latest.json", {"ts": NOW, "text": "Hallo\nZeile"})
    assert [x["id"] for x in go(tmp_path)["touched"]] == ["briefing-2026-10-27"]


def test_the_local_model_rewords_only_the_teaser_and_falls_back(tmp_path):
    put(tmp_path, "reports/pumpfun_rt/live_status.json", {"t": NOW, "running": False, "on": False,
                                                          "pnl_total_sol": -0.4766})
    calls = []

    def fake(facts, fallback, lang):
        calls.append((facts, lang))
        return "Der Bot ist aus, mit -0,477 SOL seit dem Start."
    a = arts(go(tmp_path, summarize=fake), "live-")[0]
    assert a["teaser"] == "Der Bot ist aus, mit -0,477 SOL seit dem Start." and calls[0][1] == "de"
    body_before = a["body"]

    def broken(facts, fallback, lang):
        raise TimeoutError
    put(tmp_path, "reports/pumpfun_rt/live_status.json", {"t": NOW, "running": True, "on": True, "pnl_total_sol": -0.4})
    b = arts(go(tmp_path, now=NOW + 1, summarize=broken), "live-pumpfun-an")[0]
    assert b["teaser"].startswith("Der Echtgeld-Bot für pump.fun ist eingeschaltet")
    assert body_before.startswith("## Was passiert ist")


def test_fit_bounds():
    short = news.fit("## A\n\nKurz.", "Daten")
    assert news.words(short) >= news.MIN_WORDS
    long = news.fit("\n".join(["Wort " * 40] * 30), "Forschung")
    assert news.words(long) <= news.MAX_WORDS and "gekürzt" in long
