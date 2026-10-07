"""M5 · Regime: the probability that the next 30 days hold a large BTC drawdown.

The momentum book's best friend so far is a 1970s rule: hold nothing while
BTC closes below its 200-day average. It cut the book's drawdown from 25 % to
19 % and lifted its Sharpe from 0.72 to 1.05. This asks whether a model of the
market state can do better than that one line, as a forecast and as a switch.

Event: from the close of day d, BTC trades at least 15 % below that close at
some daily close within the next 30 days. (About one monthly standard
deviation of BTC; fixed before looking at the results.)

Features at the end of day d:
  BTC trend   log distance from the 20, 50, 100 and 200-day averages, returns
              over 7, 30, 90 and 180 days, distance from the 365-day high
  BTC risk    realised volatility over 7 and 30 days (hourly-bar RV), their
              ratio, the downside share of variance
  leverage    BTC perp funding over 7 and 30 days (crowded longs pay)
  breadth     from the survivorship-free universe (M4's panel): share of
              eligible coins up over 7 and 28 days, share within 10 % of their
              28-day high, median 28-day return minus BTC's, median correlation
              with BTC, cross-sectional dispersion
Models: logistic regression on all features (L2, standardised), logistic on
four (200-day distance, 30-day vol, 30-day return, 28-day breadth), and a
shallow LightGBM classifier.
Baselines: the base rate seen in training (climatology) and the 200-day rule
as a forecast (the training frequency of the event above and below the line).

Walk-forward by quarter from 2022, embargo 31 days (label + 1). Data start in
2020, so the first model learns from about 17 months, about 17 independent
30-day windows. Scores: Brier, log loss, AUC; Diebold-Mariano on the Brier
loss against the 200-day rule with a 30-day Newey-West lag.

Then as a switch, on two books: BTC buy-and-hold and the momentum book
(momentum2's pick: 28-day, daily, 40 % vol target). Rules: hard (hold when
p < theta, theta 0.2 to 0.5) and soft (exposure scaled by 1 - p). Theta is
chosen on 2022-2023, the holdout is 2024 on. Costs 15 and 41 bps per unit of
turnover. Every rule on every book is deflated together.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import report
from ..cv import walk_forward
from ..data import HOUR_US, funding
from ..metrics import deflated_sharpe, diebold_mariano

DAY_US = 24 * HOUR_US
HORIZON = 30
DROP = -0.15
FIRST_TEST = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
HOLDOUT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
COSTS = {"15bps": 0.0015, "41bps": 0.0041}
THETAS = (0.2, 0.3, 0.4, 0.5)
FULL = ["ma20", "ma50", "ma100", "ma200", "r7", "r30", "r90", "r180", "dd365", "vol7", "vol30", "vratio",
        "dn_share30", "fund7", "fund30", "br_up7", "br_up28", "br_nearhi", "br_rel28", "br_corr", "br_disp7"]
SMALL = ["ma200", "vol30", "r30", "br_up28"]
LGB_PARAMS = dict(n_estimators=200, learning_rate=0.02, num_leaves=4, max_depth=2, min_child_samples=60,
                  subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=10.0, n_jobs=4, verbose=-1)


def btc_frame() -> pl.DataFrame:
    from .picks import daily_bars
    b = daily_bars("BTCUSDT").sort("day")
    # Calendar days, so 30 rows ahead is 30 days ahead.
    cal = pl.DataFrame({"day": np.arange(int(b["day"][0]), int(b["day"][-1]) + 1, DAY_US, dtype=np.int64)})
    b = cal.join(b, on="day", how="left").with_columns(pl.col("close").fill_null(strategy="forward"))
    lc = pl.col("close").log()
    f = b.with_columns(
        **{f"ma{k}": lc - pl.col("close").rolling_mean(k).log() for k in (20, 50, 100, 200)},
        **{f"r{k}": lc - lc.shift(k) for k in (7, 30, 90, 180)},
        dd365=lc - pl.col("close").rolling_max(365, min_samples=120).log(),
        vol7=(pl.col("rv").rolling_mean(7, min_samples=5) * 365).sqrt(),
        vol30=(pl.col("rv").rolling_mean(30, min_samples=20) * 365).sqrt(),
    ).with_columns(vratio=pl.col("vol7") / pl.col("vol30"))
    # Downside share needs signed returns: daily close-to-close as a proxy.
    ret = (lc - lc.shift(1))
    f = f.with_columns(_r=ret).with_columns(
        dn_share30=(pl.col("_r").clip(upper_bound=0) ** 2).rolling_sum(30, min_samples=20)
        / ((pl.col("_r") ** 2).rolling_sum(30, min_samples=20) + 1e-12)).drop("_r")
    # Event label: the lowest close of the next 30 days relative to today's.
    close = f["close"].to_numpy()
    n = len(close)
    worst = np.full(n, np.nan)
    for i in range(n - HORIZON):
        worst[i] = close[i + 1:i + 1 + HORIZON].min() / close[i] - 1
    f = f.with_columns(worst30=pl.Series(worst), ret1=pl.Series(np.r_[close[1:] / close[:-1] - 1, np.nan]))
    fu = funding("BTC")
    fd = (fu.with_columns(day=((pl.col("funding_time_us") - 1) // DAY_US) * DAY_US)
          .group_by("day").agg(fd=pl.col("funding_rate").sum()))
    f = f.join(fd, on="day", how="left").sort("day").with_columns(
        fund7=pl.col("fd").rolling_sum(7, min_samples=5), fund30=pl.col("fd").rolling_sum(30, min_samples=20)).drop("fd")
    return f


def breadth() -> pl.DataFrame:
    from .xs_daily import build_panel
    p = build_panel().filter("eligible")
    btc = p.filter(pl.col("symbol") == "BTCUSDT").select("day", _b28="r28")
    return (p.join(btc, on="day", how="left").group_by("day").agg(
        br_up7=(pl.col("r7") > 0).mean(), br_up28=(pl.col("r28") > 0).mean(),
        br_nearhi=(pl.col("dist_hi28") > -0.10).mean(),
        br_rel28=(pl.col("r28") - pl.col("_b28")).median(),
        br_corr=pl.col("corr56").median(), br_disp7=pl.col("r7").std(), n=pl.len())
        .filter(pl.col("n") >= 20).drop("n"))


def brier(y, p):
    return (p - y) ** 2


def switch_book(ret: np.ndarray, expo: np.ndarray, cost: float) -> tuple[np.ndarray, np.ndarray]:
    """Exposure e[t] is set at the close of day t and earns ret[t] (close t to close t+1).
    Costs on every change. Element t of the result is the P&L earned over day t+1."""
    e = np.nan_to_num(expo)
    r = np.nan_to_num(ret)
    # Yesterday's exposure after it drifted with the price, so a soft rule pays for its daily rebalance.
    prev = np.r_[0.0, e[:-1] * (1 + r[:-1]) / (1 + e[:-1] * r[:-1])]
    turn = np.abs(e - prev)
    return e * r - turn * cost, turn


def perf(r):
    r = r[np.isfinite(r)]
    eq = np.cumprod(1 + r)
    yrs = len(r) / 365
    return {"sharpe": float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0,
            "cagr": float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0,
            "max_dd": float((1 - eq / np.maximum.accumulate(eq)).max())}


def main() -> None:
    t0 = time.time()
    f = btc_frame().join(breadth(), on="day", how="left").sort("day")
    f = f.with_columns(y=(pl.col("worst30") <= DROP).cast(pl.Float64).fill_nan(None))
    f = f.with_columns(pl.when(pl.col("worst30").is_null()).then(None).otherwise(pl.col("y")).alias("y"))
    usable = f.select(pl.all_horizontal(pl.col(FULL).is_not_null())).to_series().to_numpy()
    f = f.filter(pl.Series(usable))
    days = f["day"].to_numpy()
    y = f["y"].to_numpy().astype(float)
    X = f.select(FULL).to_numpy()
    Xs = f.select(SMALL).to_numpy()
    above = f["ma200"].to_numpy() > 0
    print(f"{len(days)} usable days from {datetime.fromtimestamp(days[0] / 1e6, timezone.utc):%Y-%m-%d}, "
          f"event rate {np.nanmean(y):.2f}", flush=True)

    probs = {m: np.full(len(days), np.nan) for m in ("climatology", "ma200 rule", "logit full", "logit small", "lgbm")}
    fold_rows = []
    for fold in walk_forward(days, FIRST_TEST, embargo_h=(HORIZON + 1) * 24):
        tr = fold.train & np.isfinite(y)
        te = fold.test
        probs["climatology"][te] = y[tr].mean()
        probs["ma200 rule"][te] = np.where(above[te], y[tr & above].mean(), y[tr & ~above].mean())
        lf = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)).fit(X[tr], y[tr])
        probs["logit full"][te] = lf.predict_proba(X[te])[:, 1]
        ls = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)).fit(Xs[tr], y[tr])
        probs["logit small"][te] = ls.predict_proba(Xs[te])[:, 1]
        gb = lgb.LGBMClassifier(**LGB_PARAMS).fit(X[tr], y[tr])
        probs["lgbm"][te] = gb.predict_proba(X[te])[:, 1]
        ev = te & np.isfinite(y)
        row = {"fold": fold.name, "train_days": int(tr.sum()), "test_days": int(ev.sum()),
               "event_rate": float(y[ev].mean()) if ev.any() else None}
        for m in probs:
            row[m] = float(brier(y[ev], probs[m][ev]).mean()) if ev.any() else None
        fold_rows.append(row)
        print(row, flush=True)

    ev = np.isfinite(y) & np.isfinite(probs["lgbm"])
    score_rows = []
    for m, p in probs.items():
        b = brier(y[ev], p[ev])
        pc = np.clip(p[ev], 1e-4, 1 - 1e-4)
        ll = -np.mean(y[ev] * np.log(pc) + (1 - y[ev]) * np.log(1 - pc))
        dm, dmp = diebold_mariano(b, brier(y[ev], probs["ma200 rule"][ev]), lag=HORIZON) if m != "ma200 rule" else (0.0, 1.0)
        try:
            auc = float(roc_auc_score(y[ev], p[ev]))
        except ValueError:
            auc = None
        score_rows.append({"model": m, "brier": float(b.mean()), "log_loss": float(ll), "auc": auc,
                           "skill_vs_ma200": float(1 - b.mean() / brier(y[ev], probs["ma200 rule"][ev]).mean()),
                           "skill_vs_climatology": float(1 - b.mean() / brier(y[ev], probs["climatology"][ev]).mean()),
                           "dm_p_vs_ma200": dmp})
    # Holdout-only scores too (the window the switch is judged on).
    hv = ev & (days >= HOLDOUT)
    for r in score_rows:
        r["brier_2024_on"] = float(brier(y[hv], probs[r["model"]][hv]).mean())

    # ---- as a switch
    from .momentum2 import run
    from .tsmom import COST, daily_matrix, rolling_mean, target_weights
    mdays, close, rv, names = daily_matrix()
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc_c = close[:, names.index("BTC")]
    ma = rolling_mean(btc_c[:, None], 200, 200)[:, 0]
    ma_on = np.nan_to_num(btc_c > ma, nan=0.0)
    di = {int(d): i for i, d in enumerate(days)}
    idx = np.array([di.get(int(d), -1) for d in mdays])

    def on_series(p: np.ndarray) -> np.ndarray:
        out = np.full(len(mdays), np.nan)
        out[idx >= 0] = p[idx[idx >= 0]]
        return out

    # Momentum book with a multiplier m_t on its weights; one unit of the book costs COST per turnover.
    base_fn = lambda t: target_weights(close, sigma, history, t, [28], 0.40)  # noqa: E731
    btc_ret = np.r_[btc_c[1:] / btc_c[:-1] - 1, np.nan]

    def books(expo: np.ndarray) -> dict:
        e = np.nan_to_num(expo)
        g, c, _, _ = run(close, lambda t: base_fn(t) * e[t], 1, 200)
        paid = np.r_[0.0, c[:-1]]
        out = {}
        for cn, cv in COSTS.items():
            out[("momentum book", cn)] = g - paid * cv / COST
            out[("BTC", cn)] = switch_book(btc_ret, e, cv)[0]
            # switch_book returns day-t P&L for exposure set at t on the return t -> t+1;
            # shift it so it lines up with the momentum book's dating (P&L on day t+1).
            out[("BTC", cn)] = np.r_[0.0, out[("BTC", cn)][:-1]]
        out[("momentum book", "turnover")] = c / COST
        out[("BTC", "turnover")] = switch_book(btc_ret, e, 0.0)[1]
        return out

    sel = (mdays >= FIRST_TEST) & (mdays < HOLDOUT)
    hold = mdays >= HOLDOUT
    yrs_all = (sel | hold).sum() / 365
    rules = {"always on": np.ones(len(mdays)), "ma200 switch": ma_on}
    for m in ("logit full", "logit small", "lgbm"):
        p = on_series(probs[m])
        # Before the first fold has a forecast, fall back to the 200-day rule (identical for every model).
        for th in THETAS:
            rules[f"{m} · p < {th}"] = np.where(np.isfinite(p), (p < th).astype(float), ma_on)
        rules[f"{m} · soft 1 - p"] = np.where(np.isfinite(p), 1 - p, ma_on)
    rows = []
    for name, expo in rules.items():
        b = books(expo)
        for bk in ("BTC", "momentum book"):
            row = {"book": bk, "rule": name, "turnover_yr": float(b[(bk, "turnover")][hold].sum() / (hold.sum() / 365))}
            for cn in COSTS:
                r = b[(bk, cn)]
                ps, ph = perf(r[sel]), perf(r[hold])
                row[f"sel_sharpe_{cn}"] = ps["sharpe"]
                row[f"hold_sharpe_{cn}"] = ph["sharpe"]
                row[f"hold_cagr_{cn}"] = ph["cagr"]
                row[f"hold_max_dd_{cn}"] = ph["max_dd"]
            row["avg_exposure_hold"] = float(np.nan_to_num(expo)[hold].mean())
            rows.append(row)
    n_obs = int(hold.sum())
    for cn in COSTS:
        srs = np.array([r[f"hold_sharpe_{cn}"] for r in rows]) / np.sqrt(365)
        for r in rows:
            r[f"deflated_p_{cn}"] = deflated_sharpe(r[f"hold_sharpe_{cn}"] / np.sqrt(365), n_obs, len(rows), float(np.var(srs)))

    lines = []
    for bk in ("BTC", "momentum book"):
        br = [r for r in rows if r["book"] == bk]
        ma_row = next(r for r in br if r["rule"] == "ma200 switch")
        on_row = next(r for r in br if r["rule"] == "always on")
        best = max((r for r in br if r["rule"] not in ("always on", "ma200 switch")), key=lambda r: r["sel_sharpe_15bps"])
        passes = (best["deflated_p_15bps"] > 0.95 and best["hold_sharpe_41bps"] > ma_row["hold_sharpe_41bps"]
                  and best["hold_max_dd_15bps"] < ma_row["hold_max_dd_15bps"])
        best["passes"] = passes
        lines.append(f"- **{bk}**: always on, holdout Sharpe {on_row['hold_sharpe_15bps']:.2f}, drawdown "
                     f"{on_row['hold_max_dd_15bps'] * 100:.0f} %; 200-day switch {ma_row['hold_sharpe_15bps']:.2f} / "
                     f"{ma_row['hold_sharpe_41bps']:.2f} (15 / 41 bps), drawdown {ma_row['hold_max_dd_15bps'] * 100:.0f} %. "
                     f"Model rule picked on 2022-2023: *{best['rule']}*, holdout {best['hold_sharpe_15bps']:.2f} / "
                     f"{best['hold_sharpe_41bps']:.2f}, drawdown {best['hold_max_dd_15bps'] * 100:.0f} %, deflated p "
                     f"{best['deflated_p_15bps']:.2f}. " + ("Beats the 200-day rule." if passes else "Does not beat the 200-day rule."))
    sm = {r["model"]: r for r in score_rows}
    best_fc = min((r for r in score_rows if r["model"] not in ("climatology", "ma200 rule")), key=lambda r: r["brier"])
    verdict = (f"Event rate {np.nanmean(y[ev]):.2f} out of sample. Best forecast: {best_fc['model']}, Brier "
               f"{best_fc['brier']:.3f} against {sm['ma200 rule']['brier']:.3f} for the 200-day rule and "
               f"{sm['climatology']['brier']:.3f} for the base rate (skill vs the rule {best_fc['skill_vs_ma200'] * 100:.1f} %, "
               f"DM p {best_fc['dm_p_vs_ma200']:.2f}).")
    md = (
        "# M5 · Regime: large BTC drawdown in the next 30 days\n\n"
        f"Event: a daily close at least {-DROP * 100:.0f} % below today's within {HORIZON} days. {len(days)} days "
        f"with every feature, out of sample from 2022 ({int(ev.sum())} scored days, about {int(ev.sum() / HORIZON)} "
        f"independent windows). Took {(time.time() - t0) / 60:.1f} min.\n\n**Verdict:** {verdict}\n\n"
        + "\n".join(lines) + "\n\n## Forecast scores out of sample\n\n"
        + report.table(score_rows, ["model", "brier", "brier_2024_on", "log_loss", "auc", "skill_vs_ma200",
                                    "skill_vs_climatology", "dm_p_vs_ma200"])
        + f"\n## Switch rules on both books (sel = 2022-2023, hold = 2024 on), {len(rows)} variants deflated together\n\n"
        + report.table(rows, ["book", "rule", "sel_sharpe_15bps", "hold_sharpe_15bps", "hold_sharpe_41bps",
                              "hold_cagr_15bps", "hold_max_dd_15bps", "turnover_yr", "avg_exposure_hold",
                              "deflated_p_15bps", "deflated_p_41bps"])
        + "\n## Brier per quarter\n\n"
        + report.table(fold_rows, ["fold", "train_days", "test_days", "event_rate", "climatology", "ma200 rule",
                                   "logit full", "logit small", "lgbm"])
    )
    report.write("regime", md, {"scores": score_rows, "rows": rows, "folds": fold_rows, "years": yrs_all})


if __name__ == "__main__":
    main()
