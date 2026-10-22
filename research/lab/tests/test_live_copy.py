"""The live twins: the same signal under an id of their own, never from a stale original."""

import json

from lab.paper import live_copy as LC

SIG = {"strategy": "breakout_top10", "variant": "Donchian 20/10", "as_of_ms": 1, "generated_ms": 2,
       "valid_until_ms": 10_000, "quote": "USD", "weights": {"NEAR": 0.1}, "autopilot_only": True,
       "evidence": {"deflated_p": 0.01}}


def write(root, sig):
    d = root / "signals" / sig["strategy"]
    d.mkdir(parents=True)
    (d / "latest.json").write_text(json.dumps(sig), encoding="utf-8")


def test_the_twin_carries_the_same_book_under_its_own_id(tmp_path):
    write(tmp_path, SIG)
    assert LC.write_twins(tmp_path, ["breakout_top10"], now_ms=5_000) == ["breakout_top10_live"]
    t = json.loads((tmp_path / "signals" / "breakout_top10_live" / "latest.json").read_text(encoding="utf-8"))
    assert t["strategy"] == "breakout_top10_live" and t["live_copy_of"] == "breakout_top10"
    assert t["variant"].endswith("(live copy)")
    for k in ("weights", "evidence", "valid_until_ms", "autopilot_only", "quote"):
        assert t[k] == SIG[k]


def test_a_stale_or_missing_original_writes_no_twin(tmp_path):
    write(tmp_path, SIG)
    assert LC.write_twins(tmp_path, ["breakout_top10"], now_ms=20_000) == []
    assert LC.write_twins(tmp_path, ["tsmom_top20"], now_ms=5_000) == []
    assert not (tmp_path / "signals" / "breakout_top10_live").exists()
