import json

from lab.ops import paper_books


def _write(root, rel, d):
    p = root / "reports" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def _fake(root):
    _write(root, "pumpfun_rt/realistic.json", {
        "realistic_since": 1792806196009, "factory": [],
        "small": [{"book": "P_x_sw10o3n", "strategy": "P_x", "sol": 0.54}]})
    _write(root, "smallaccount/latest.json", {"books": {"small50_tsmom1": {
        "variant": "EXPERIMENT, paper only · S1 small account · 50 EUR paper wallet · 28d momentum · daily",
        "started": "2026-10-24T04:16:44+00:00", "equity_eur": 48.9}}})
    _write(root, "onchain_longterm/latest.json", {"book": "onchain_longterm", "equity_usdc": 50.26})
    _write(root, "forward/latest.json", {"books": [
        {"kind": "book", "name": "tsmom", "label": "Momentum, 20 coins", "since": "2026-10-06",
         "return_pct": -6.4},
        {"kind": "book", "name": "onchain_longterm", "since": "2026-10-26", "return_pct": -0.1}]})


def test_a_book_from_each_report(tmp_path):
    _fake(tmp_path)
    by = {b["name"]: b for b in paper_books.books(tmp_path)}
    assert set(by) == {"P_x_sw10o3n", "small50_tsmom1", "onchain_longterm", "tsmom"}
    assert by["P_x_sw10o3n"]["study"] == "R2" and by["P_x_sw10o3n"]["currency"] == "SOL"
    assert by["P_x_sw10o3n"]["start"] == "2026-10-24" and by["P_x_sw10o3n"]["value"] == 0.54
    assert by["small50_tsmom1"]["study"] == "S1" and by["small50_tsmom1"]["trades"] == "28d momentum"
    assert by["small50_tsmom1"]["start"] == "2026-10-24" and by["small50_tsmom1"]["currency"] == "EUR"
    assert by["onchain_longterm"]["study"] == "L1" and by["onchain_longterm"]["start"] == "2026-10-26"
    assert by["onchain_longterm"]["value"] == 50.26
    assert by["tsmom"]["study"] == "forward" and by["tsmom"]["report"] == "forward/latest.json"


def test_missing_reports_are_skipped(tmp_path):
    assert paper_books.books(tmp_path) == []
    _write(tmp_path, "forward/latest.json", {"books": [{"name": "tsmom", "return_pct": 1.0}]})
    (tmp_path / "reports" / "smallaccount").mkdir()
    (tmp_path / "reports" / "smallaccount" / "latest.json").write_text("not json")
    assert [b["name"] for b in paper_books.books(tmp_path)] == ["tsmom"]


def test_table_has_one_row_per_book(tmp_path):
    _fake(tmp_path)
    assert paper_books.main(tmp_path) == 0
    md = (tmp_path / "reports" / "paper_books" / "latest.md").read_text(encoding="utf-8")
    rows = [line for line in md.splitlines() if line.startswith("| ") and not line.startswith("| Book")]
    assert len(rows) == 4
    assert "48.90 EUR" in md and "0.54 SOL" in md
