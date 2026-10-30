"""DT1, day trading on every liquid listed coin: the universe, the minute sigma, the candidates, fills and exits,
the position cap, funding, the costs and the trials. Synthetic data only, no lab data.

Run from research/lab:  python -m pytest tests/test_daytrade_dt1.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab import leak
from lab.experiments import daytrade_dt1 as dt

DAY = dt.DAY_MIN


def daily_frame(rows: dict[str, list[tuple[str, float]]]) -> pl.DataFrame:
    """{symbol: [(day, quote volume)]} as load_daily's frame (price 100)."""
    out = []
    for s, xs in rows.items():
        for d, q in xs:
            out.append({"symbol": s, "day": dt.dnum(d), "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "qv": q})
    return pl.DataFrame(out)


def run_days(first: str, n: int, q: float) -> list[tuple[str, float]]:
    d0 = np.datetime64(first, "D")
    return [(str(d0 + np.timedelta64(k, "D")), q) for k in range(n)]


def month(n_days: int = 3, M: int = 2, seed: int = 0, sigma: float = 1e-3) -> dt.Month:
    """A synthetic Month: n_days days after the warm-up day, M coins on a random walk, open = previous close."""
    rng = np.random.default_rng(seed)
    T = (n_days + 1) * DAY
    r = rng.normal(0, sigma, (M, T))
    c = 100 * np.exp(np.cumsum(r, 1))
    o = np.c_[np.full((M, 1), 100.0), c[:, :-1]]
    h = np.maximum(o, c) * (1 + 2e-4)
    l = np.minimum(o, c) * (1 - 2e-4)
    qv = np.full((M, T), 1e6)
    tb = qv * 0.5
    m0 = dt.dnum("2025-03-01") * DAY
    f = lambda x: x.astype(np.float32)                                         # noqa: E731
    return dt.Month("2025-03", [f"C{k}USDT" for k in range(M)], np.arange(M), m0, f(o), f(h), f(l), f(c), f(qv), f(tb))


def ctx(P: dt.Month, er: float = 0.05) -> dt.Ctx:
    dt.derive(P)
    nd = P.nd
    one = np.ones((P.M, nd), dtype=bool)
    return dt.Ctx(P, dt.so_far(P), one.copy(), one.copy(), one.copy(), np.full((P.M, nd), er),
                  np.full((P.M, nd), 100.0), np.full((P.M, nd), 101.0), np.full((P.M, nd), 99.0),
                  np.full((P.M, nd), 1e8), np.full((P.M, nd), dt.SLIP_BASE), [None] * P.M, [None] * P.M, 0)


# ---------------------------------------------------------------- the universe

def test_exclusions_keep_memecoins():
    for s in ("USDCUSDT", "FDUSDUSDT", "PAXGUSDT", "XAUUSDT", "BTCDOMUSDT", "DEFIUSDT", "TSLAUSDT", "SPYUSDT",
              "NVDAUSDT", "BTCUPUSDT", "ETHDOWNUSDT", "USDBRLUSDT"):
        assert dt.excluded(s), s
    for s in ("BTCUSDT", "DOGEUSDT", "1000PEPEUSDT", "WIFUSDT", "SUIUSDT", "1000SHIBUSDT"):
        assert not dt.excluded(s), s


def test_hyperliquid_tickers_map_to_binance():
    assert dt.hl_to_binance("kPEPE") == "1000PEPEUSDT"
    assert dt.hl_to_binance("BTC") == "BTCUSDT"
    assert dt.hl_to_binance("kBONK") == "1000BONKUSDT"


def test_qualifies_needs_180_days_and_30_days_of_volume_before_the_day():
    f = daily_frame({"AUSDT": run_days("2022-01-01", 400, 60e6), "BUSDTX": run_days("2022-01-01", 400, 40e6),
                     "USDCUSDT": run_days("2022-01-01", 400, 1e9)})
    Dy = dt.to_daily(f)
    Q = dt.qualifies(Dy)
    a, b, u = Dy.names.index("AUSDT"), Dy.names.index("BUSDTX"), Dy.names.index("USDCUSDT")
    assert not Q[179, a] and Q[180, a]              # day 180 is the first with 180 days listed before it
    assert not Q[:, b].any()                        # 40 M is under the bar
    assert Q[:, b].sum() == 0 and dt.qualifies(Dy, 20e6)[200, b]
    assert not Q[:, u].any()                        # a stablecoin never


def test_trailing_volume_excludes_the_day_itself():
    qv = np.r_[np.full(30, 10.0), 1e9][:, None]
    v = dt.trailing_volume(qv)
    assert v[30, 0] == pytest.approx(10.0)          # the 1e9 day is not in its own window
    assert np.isnan(v[29, 0])


def test_a_gap_restarts_the_listing_clock_and_delisted_days_are_out():
    xs = run_days("2022-01-01", 200, 60e6) + run_days("2022-09-01", 220, 60e6)
    Dy = dt.to_daily(daily_frame({"AUSDT": xs}))
    Q = dt.qualifies(Dy)
    r = lambda d: dt.dnum(d) - Dy.d0                                           # noqa: E731
    assert Q[r("2022-07-15"), 0]                    # 195 days into the first segment
    assert not Q[r("2022-08-15"), 0]                # delisted: no bars, out
    assert not Q[r("2022-12-01"), 0]                # the new segment is 91 days old
    assert Q[r("2023-03-10"), 0]


def test_listed_mask_by_first_and_last_day():
    Dy = dt.to_daily(daily_frame({"AUSDT": run_days("2023-01-01", 30, 1.0)}))
    m = dt.listed_mask(Dy, {"AUSDT": (dt.dnum("2023-01-10"), dt.dnum("2023-01-20"))})
    assert m[:, 0].sum() == 11 and m[9, 0] and not m[8, 0] and not m[20, 0]


def test_har_pk_uses_only_days_before():
    rng = np.random.default_rng(1)
    rows = {}
    for s in ("AUSDT", "BUSDT"):
        n = 1100
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
        rows[s] = c
    out = []
    d0 = dt.dnum("2020-01-01")
    for s, c in rows.items():
        for k, x in enumerate(c):
            w = abs(rng.normal(0, 0.02)) + 0.005
            out.append({"symbol": s, "day": d0 + k, "o": x, "h": x * (1 + w), "l": x * (1 - w), "c": x, "qv": 1e8})
    Dy = dt.to_daily(pl.DataFrame(out))
    er = dt.har_pk(Dy, "2022-01-01", "2022-12-31")
    k = dt.dnum("2022-05-10") - Dy.d0
    assert np.isfinite(er[k]).all()
    Dy.h[k:, 0] *= 1.5                              # the day itself and later changed: its forecast does not move
    er2 = dt.har_pk(Dy, "2022-01-01", "2022-12-31")
    np.testing.assert_allclose(er2[k], er[k])
    assert not np.allclose(er2[k + 1, 0], er[k + 1, 0])


# ---------------------------------------------------------------- minutes

def test_sigma_and_z_use_the_minutes_before_only():
    P = month(n_days=2, M=1)
    dt.derive(P)
    t = DAY + 500
    r = P.ex["r"][0]
    want = math.sqrt(np.nanmean(r[t - dt.SIG_N:t] ** 2))
    assert P.ex["sig"][0, t] == pytest.approx(want, rel=1e-9)
    assert P.ex["z"][0, t] == pytest.approx(r[t] / want, rel=1e-9)


def test_minute_features_pass_the_leak_harness():
    P0 = month(n_days=2, M=2, seed=4)
    data = {"days": np.arange(P0.T), **{k: getattr(P0, k).T.copy() for k in ("o", "h", "l", "c", "qv", "tb")}}

    def fn(X):
        P = dt.Month("2025-03", P0.names, P0.jd, P0.m0, *(X[k].T.copy() for k in ("o", "h", "l", "c", "qv", "tb")))
        C = ctx(P)
        F = dt.p_features(C)
        out = np.full((P.T, P.M, len(dt.FEATS)), np.nan)
        out[F["t"] - P.m0, F["sym_row"]] = F["X"]
        return {"sig": C.P.ex["sig"].T, "z": C.P.ex["z"].T, "vz": C.P.ex["vz"].T, "feat": out}
    # a month is whole days, so the harness's truncated (recursive) copies do not apply
    res = leak.check(fn, data, cuts=[DAY + 300, DAY + 1000, 2 * DAY + 100], kinds=("shuffle", "nan"),
                     recursive=False, name="dt1")
    assert res["ok"], res


def test_p_targets_end_by_the_cut():
    C = ctx(month(n_days=1, M=1))
    F = dt.p_features(C)
    mod = (F["t"] - C.P.m0) % DAY
    late = mod + 1 + 60 > dt.CUT_MIN
    assert np.isnan(F["y60"][late]).all() and np.isfinite(F["y60"][~late]).any()
    assert (mod + 1 < dt.CUT_MIN).all() and (mod % 15 == 14).all()


# ---------------------------------------------------------------- fills, exits, the cap

def flat_ctx(price: float = 100.0, n_days: int = 1, M: int = 1) -> dt.Ctx:
    P = month(n_days=n_days, M=M)
    for k in ("o", "h", "l", "c"):
        getattr(P, k)[:] = price
    P.h[:] = price * (1 + 1e-5)
    P.l[:] = price * (1 - 1e-5)
    return ctx(P)


def one(j=0, t=DAY + 100, side=1.0, ds=0.01, hold=10, tkd=np.nan, tkl=np.nan) -> dict:
    return dt.cand([j], [t], [side], [1.0], [ds], hold, tkd=[tkd], tkl=[tkl])


def test_taker_entry_at_the_next_open_and_time_exit():
    C = flat_ctx()
    t = DAY + 100
    C.P.o[0, t + 1] = 100.0
    C.P.o[0, t + 11] = 101.0
    dt.derive(C.P)
    o = dt.outcomes(C, one(t=t, hold=10), 1, False)
    assert o["ok"][0] and o["t_in"][0] == t + 1 and o["t_out"][0] == t + 11
    assert o["gross"][0] == pytest.approx(0.01, rel=1e-5)
    assert o["notional"][0] == pytest.approx(dt.RISK / 0.01)
    late = dt.outcomes(C, one(t=t, hold=10), 2, False)
    assert late["t_in"][0] == t + 2


def test_stop_fills_at_the_stop_or_a_worse_open():
    C = flat_ctx()
    t = DAY + 100
    C.P.l[0, t + 3] = 98.5                          # through the 1 % stop at 99
    o = dt.outcomes(C, one(t=t, ds=0.01, hold=30), 1, False)
    assert o["stop"][0] and o["gross"][0] == pytest.approx(-0.01, rel=1e-4) and o["t_out"][0] == t + 4
    C.P.o[0, t + 3] = 98.0                          # gapped through it
    dt.derive(C.P)
    o = dt.outcomes(C, one(t=t, ds=0.01, hold=30), 1, False)
    assert o["gross"][0] == pytest.approx(-0.02, rel=1e-4)


def test_stop_wins_when_a_minute_touches_both():
    C = flat_ctx()
    t = DAY + 100
    C.P.l[0, t + 2], C.P.h[0, t + 2] = 98.0, 103.0
    o = dt.outcomes(C, one(t=t, ds=0.01, hold=30, tkd=0.02), 1, False)
    assert o["stop"][0] and not o["take"][0]


def test_everything_is_out_by_2355_and_no_entry_after():
    C = flat_ctx()
    t = DAY + dt.CUT_MIN - 10
    o = dt.outcomes(C, one(t=t, hold=240), 1, False)
    assert o["ok"][0] and o["t_out"][0] == DAY + dt.CUT_MIN
    o = dt.outcomes(C, one(t=DAY + dt.CUT_MIN - 1, hold=5), 1, False)
    assert not o["ok"][0]


def test_universe_days_only():
    C = flat_ctx()
    C.qual[0, 1] = False
    assert not dt.outcomes(C, one(), 1, False)["ok"][0]


def test_maker_entry_needs_a_trade_through():
    C = flat_ctx()
    t = DAY + 100
    o = dt.outcomes(C, one(t=t), 1, True)
    assert not o["ok"][0]                           # the price never trades 1 bp through the limit: missed
    C.P.l[0, t + 2] = 100 * (1 - 5e-4)              # 5 bps through: half the order
    o = dt.outcomes(C, one(t=t), 1, True)
    assert o["ok"][0] and o["t_in"][0] == t + 2 and o["ent_taker"][0] == 0
    assert o["notional"][0] == pytest.approx(0.5 * dt.RISK / 0.01, rel=1e-3)
    C.P.l[0, t + 2] = 100 * (1 - 0.5e-4)            # half a bp: not enough
    assert not dt.outcomes(C, one(t=t), 1, True)["ok"][0]


def test_take_level_must_be_beyond_the_entry():
    C = flat_ctx()
    assert not dt.outcomes(C, one(tkl=99.0), 1, False)["ok"][0]
    assert dt.outcomes(C, one(tkl=101.0), 1, False)["ok"][0]


def test_greedy_caps_positions_and_one_per_coin():
    t_in = np.array([0, 0, 0, 0, 0, 0, 1, 5, 5])
    t_out = np.array([5, 5, 5, 5, 5, 5, 6, 9, 9])
    j = np.array([0, 1, 2, 3, 4, 5, 6, 0, 0])
    prio = np.array([1, 2, 3, 4, 5, 6, 1, 1, 2.0])
    take = dt.greedy(t_in, t_out, j, prio, n_pos=5)
    assert take[:6].sum() == 5 and not take[0]      # the lowest priority of six is dropped
    assert not take[6]                              # still full at minute 1
    assert take[8] and not take[7]                  # slots free at 5; coin 0 once, by priority


def test_funding_strictly_between_entry_and_exit():
    mins = np.array([100, 200, 300])
    F = [(mins, np.r_[0.0, np.cumsum([0.001, 0.002, 0.004])])]
    j = np.zeros(3, dtype=np.int64)
    got = dt.funding_between(F, j, np.array([50, 100, 150]), np.array([250, 300, 350]))
    np.testing.assert_allclose(got, [0.003, 0.002, 0.006])


# ---------------------------------------------------------------- costs and the book

def test_break_even_fee_zeroes_the_net():
    C = flat_ctx(M=2)
    t = DAY + 100
    C.P.o[:, t + 11] = 100.2
    dt.derive(C.P)
    cd = dt.cand([0, 1], [t, t], [1.0, 1.0], [1.0, 2.0], [0.01, 0.01], 10)
    o = dt.outcomes(C, cd, 1, False)
    A = dt.day_stats(o, o["ok"], "bn", C.P.nd)
    s = dt.summarize(A, "hl")
    assert s["trades"] == 2 and s["gross_bps"] == pytest.approx(20, rel=1e-3)
    assert s["net_bps"] == pytest.approx(20 - 2 * (4.5 + 1), rel=1e-3)
    assert s["fee_be_bps"] == pytest.approx((20 - 2) / 2, rel=1e-3)
    per, book = dt.net_parts(A, "kf")
    assert per.sum() / 2 * 1e4 == pytest.approx(20 - 2 * (5 + 1), rel=1e-3)
    assert book.sum() == pytest.approx(2 * dt.RISK / 0.01 * (0.002 - 2 * 6e-4), rel=1e-3)


def test_slippage_is_one_bp_in_the_top_20_and_more_outside():
    Dy = dt.to_daily(daily_frame({f"C{k}USDT": run_days("2024-01-01", 40, 1e8 * (k + 1)) for k in range(22)}))
    W = dt.World(Dy, np.ones(Dy.c.shape, bool), np.ones(Dy.c.shape, bool), np.ones(Dy.c.shape, bool),
                 np.full(Dy.c.shape, 0.05), dt.trailing_volume(Dy.qv), np.zeros(Dy.c.shape, bool), {}, {})
    W.top[:, 2:] = True                             # C0 and C1 are outside the top 20
    ar = {}
    for j in range(22):
        for d in range(Dy.d0, Dy.d0 + 40):
            ar[(j, d)] = ((4e-4 if j == 0 else 1e-4) ** 2 * 100, 100)
    s = dt.slip_table(W, ar)
    assert s[35, 5] == dt.SLIP_BASE and s[35, 1] == pytest.approx(dt.SLIP_BASE)
    assert s[35, 0] == pytest.approx(dt.SLIP_BASE + (4e-4 - 1e-4) / 2)


def test_spike_candidates_side_and_stop():
    P = month(n_days=2, M=2, seed=2)
    P.c[1, DAY + 700] *= 1.02                       # one big up minute
    P.o[1, DAY + 701] = P.c[1, DAY + 700]
    C = ctx(P)
    r = dt.parse_rule("S-own:k6:none:fade:H15")
    cd = dt.cand_spike(C, r)
    k = np.flatnonzero((cd["j"] == 1) & (cd["t"] == DAY + 700))
    assert len(k) == 1 and cd["side"][k[0]] == -1
    assert cd["ds"][k[0]] == pytest.approx(3 * C.P.ex["sig"][1, DAY + 700] * math.sqrt(15))


def test_lead_lag_trades_the_quiet_alt_in_btcs_direction():
    P = month(n_days=2, M=3, seed=5)
    P.c[0, DAY + 900:] *= 0.98                      # coin 0 is BTC here: a big down minute
    P.o[0, DAY + 901:] *= 0.98
    C = ctx(P)
    cd = dt.cand_lead(C, dt.parse_rule("S-lead:k6:H5"))
    k = cd["t"] == DAY + 900
    assert set(cd["j"][k]) <= {1, 2} and (cd["side"][k] == -1).all() and k.any()


def test_rules_and_trials():
    R = dt.rules()
    assert len(R) == 164 and len(set(R)) == 164
    T = dt.trials({})
    assert len(T) == 656 and len({t["id"] for t in T}) == 656
    assert all(t["id"].startswith("hand:dt1:") and t["family"] == "hand" for t in T)
    assert dt.parse_rule("S-own:k4:taker:cont:bracket")["H"] == dt.BR_H
    assert dt.parse_rule("P-gbm:H60:m10")["m"] == pytest.approx(10e-4)
    assert dt.parse_rule("D-vwap:m0.25")["m"] == 0.25
