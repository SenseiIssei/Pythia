"""R2: the training labels at the realistic entry and exit (results/pumpfun_smallwallet_r2_prereg.md). PAPER ONLY.

R1 made the realistic execution model the paper default (realistic.py); the models were still trained on labels made
at the old latency (a buy 0.4 to 3 s after the decision). Here the same labels at R1's execution, next to the old ones:

  decision rows   (sim.Engine, models.md) win30, win300 (net30, net300), up10, up30, up120 as `<label>_r`: the buy of
                  0.1 SOL lands the drawn buy latency after the decision (key ("model", mint, offset, "buy")), a
                  drawn failure loses its live fee, the fill is at the state of the coin's first recorded trade at
                  or after the landing (that trade included), else FILL_WAIT_MS later as it stands, the cost limit
                  as before; sold at the later of decision + h and the fill, landing one drawn sale latency later,
                  filled the same way; the fee per transaction the live one with the tip. up_h: the price h s after
                  the fill above the fill price. dump60, mig, sell10_*: no execution in them, unchanged.
  early rows      (early.Tracker, X14) peak3x_r, peak10x_r: the buy lands as above (key ("early", mint, kind, "buy")),
                  its value net of the realistic sale fee reaches 3x (10x) its cost and fee within an hour of the fill.
  select rows     (selfeat.LabelPipe, Y9/Y10) RealLabelPipe: P_pool0 at entries 0 and 5 through realistic.RealExecutor
                  at 0.1 SOL; rug: the pool price at or under half the price at the drawn landing within RUG_MS after.

The engine carries a Labels as `eng.r2` (None: off, the old rows only); the study sets it in its second pass. The
daily retrain trains every model on these labels under its usual name and the old ones as `<name>_ideal` (in
models/pumpfun_rt/ideal/, never read by a book) until IDEAL_UNTIL_MS. Nothing here can trade.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import curve as C
from . import realistic as R
from . import selfeat as SF

STAKE = 100_000_000                          # 0.1 SOL, as the old labels
FILL_WAIT_MS = R.FILL_WAIT_MS
H = (30, 300)                                # sim.LABEL_HORIZONS
UP = (10, 30, 120)                           # sim.UP_HORIZONS
PEAKS = (3.0, 10.0)                          # early.PEAKS
PEAK_H_MS = 3_600_000                        # early.PEAK_H_MS
ROW_R = [f"{k}{h}_r" for h in H for k in ("win", "net")] + [f"up{h}_r" for h in UP]
EARLY_R = ["filled_r"] + [f"peak{int(k)}x_r" for k in PEAKS]
# a model's label -> its realistic column (the labels not here have no execution in them)
REAL_ROW = {"win30": "win30_r", "win300": "win300_r", "up10": "up10_r", "up30": "up30_r", "up120": "up120_r"}
REAL_EARLY = {"peak3x": "peak3x_r", "peak10x": "peak10x_r"}
IDEAL_UNTIL_MS = int(datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp() * 1000)
IDEAL = "_ideal"


def ideal_on(now_ms: float) -> bool:
    """The _ideal twins are trained until IDEAL_UNTIL_MS (two weeks from R2's deploy)."""
    return now_ms < IDEAL_UNTIL_MS


class Labels:
    """The realistic decision-row and early-row labels of one engine (eng.r2). The engine calls decide() for every
    decision row, early() for every early row and on_trade() after every curve or pool trade it took."""

    def __init__(self, eng, model: R.Model):
        self.eng, self.model = eng, model
        self.wait: dict[str, list] = {}          # mint -> [[fn, data, done]] landed, waiting for the coin's next trade
        self.peaks: dict[str, list] = {}         # mint -> [[idx, tokens, cost_l, until, peak_v]] the early fills

    # ------------------------------------------------------------ the fill at the first trade after the landing
    def fill_after(self, mint: str, land: float, fn, data) -> None:
        self.eng.push(land, "pipe", (self, "_landed", (mint, fn, data)))

    def _landed(self, at: float, x) -> None:
        mint, fn, data = x
        item = [fn, data, False]
        self.wait.setdefault(mint, []).append(item)
        self.eng.push(at + FILL_WAIT_MS, "pipe", (self, "_due", (mint, item)))

    def _due(self, at: float, x) -> None:
        mint, item = x
        if item[2]:
            return
        item[2] = True
        w = self.wait.get(mint)
        if w is not None:
            w.remove(item)
            if not w:
                self.wait.pop(mint, None)
        item[0](at, item[1])

    def on_trade(self, mint: str, t: float) -> None:
        w = self.wait.pop(mint, None) if self.wait else None
        for item in w or ():
            if not item[2]:
                item[2] = True
                item[0](t, item[1])
        ps = self.peaks.get(mint) if self.peaks else None
        if ps:
            self._peak_point(mint, ps, t)

    def _buy(self, key: tuple, at: float, mint: str, fn, failed, data) -> None:
        f = self.model.fit
        land = at + f.buy.quantile(R.u_of(key))
        kind = f.draw_fail(R.u_of(key + ("fail",)))
        if kind is not None:
            self.eng.push(land, "pipe", (self, "_call", (failed, (data, f.failed_l(kind)))))
        else:
            self.fill_after(mint, land, fn, data)

    @staticmethod
    def _call(at: float, x) -> None:
        fn, data = x
        fn(at, data)

    # ------------------------------------------------------------ decision rows
    def decide(self, idx: int, row: dict, at: float) -> None:
        st = {"idx": idx, "mint": row["mint"], "t": float(at), "off": row["off"], "price_at": row["price_at"]}
        self._buy(("model", row["mint"], row["off"], "buy"), at, row["mint"], self._row_fill, self._row_failed, st)

    def _set(self, idx: int, col: str, v: float) -> None:
        self.eng.rows.set(idx, col, float(v))

    def _row_failed(self, at: float, x) -> None:
        st, fee = x
        for h in H:
            self._set(st["idx"], f"win{h}_r", 0.0)
            self._set(st["idx"], f"net{h}_r", -fee / STAKE)

    def _row_fill(self, at: float, st: dict) -> None:
        eng, f = self.eng, self.model.fit
        tok = eng.tokens.get(st["mint"])
        if tok is None or not tok.on_curve or tok.price() > st["price_at"] * (1 + eng.costs.slip_tol):
            return self._row_failed(at, (st, f.failed_l()))
        n = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, tok.fee_bps)
        if n <= 0:
            return self._row_failed(at, (st, f.failed_l()))
        st["tokens"], st["entry_p"] = n, tok.price()
        for h in UP:
            eng.push(at + h * 1000, "pipe", (self, "_row_up", (st, h)))
        for h in H:
            dec = max(st["t"] + h * 1000, at)
            key = ("model", st["mint"], st["off"], h, "sell")
            eng.push(dec + f.sell.quantile(R.u_of(key)), "pipe", (self, "_row_sell_land", (st, h)))

    def _row_up(self, at: float, x) -> None:
        st, h = x
        tok = self.eng.tokens.get(st["mint"])
        if tok is not None and st["entry_p"] > 0 and tok.price() > 0:
            self._set(st["idx"], f"up{h}_r", tok.price() > st["entry_p"])

    def _row_sell_land(self, at: float, x) -> None:
        self.fill_after(x[0]["mint"], at, self._row_sold, x)

    def _row_sold(self, at: float, x) -> None:
        st, h = x
        v = self.eng.sale_value(self.eng.tokens.get(st["mint"]), st["tokens"])
        if v is None:
            return                                           # completed, no pool seen: unknown, stays NaN
        net = (v - STAKE - 2 * self.model.fit.tx_l()) / STAKE
        self._set(st["idx"], f"net{h}_r", net)
        self._set(st["idx"], f"win{h}_r", net > 0)

    # ------------------------------------------------------------ early rows (X14)
    def early(self, tracker, idx: int, mint: str, kind: str, want: int, at: float) -> None:
        st = {"tr": tracker, "idx": idx, "mint": mint, "want": want}
        self._buy(("early", mint, kind, "buy"), at, mint, self._early_fill, self._early_failed, st)

    def _early_failed(self, at: float, x) -> None:
        st = x[0]
        st["tr"].rows.set(st["idx"], "filled_r", 0.0)
        for k in PEAKS:
            st["tr"].rows.set(st["idx"], f"peak{int(k)}x_r", 0.0)

    def _early_fill(self, at: float, st: dict) -> None:
        tok = self.eng.tokens.get(st["mint"])
        n, cost, why = st["tr"]._cost(tok, st["want"])
        if why is not None:
            return self._early_failed(at, (st, 0))
        st["tr"].rows.set(st["idx"], "filled_r", 1.0)
        p = [st, n, cost, at + PEAK_H_MS, -math.inf]
        ps = self.peaks.setdefault(st["mint"], [])
        ps.append(p)
        self._peak_point(st["mint"], [p], at)
        self.eng.push(at + PEAK_H_MS, "pipe", (self, "_peak_end", p))

    def _peak_point(self, mint: str, ps: list, t: float) -> None:
        from .early import sale
        tok = self.eng.tokens.get(mint)
        if tok is None:
            return
        if tok.on_curve:
            venue, x, y, fee = 0, tok.vs, tok.vt, tok.fee_bps
        elif tok.pq and tok.pb:
            venue, x, y, fee = 1, tok.pb, tok.pq, tok.amm_fee_bps
        else:
            return
        tx = self.model.fit.tx_l()
        for p in ps:
            if t <= p[3]:
                v = sale(p[1], venue, x, y, fee) - tx
                if v == v and v > p[4]:
                    p[4] = v

    def _peak_end(self, at: float, p: list) -> None:
        st = p[0]
        ps = self.peaks.get(st["mint"])
        if ps is not None:
            ps.remove(p)
            if not ps:
                self.peaks.pop(st["mint"], None)
        cost = p[2] + self.model.fit.tx_l()
        for k in PEAKS:
            st["tr"].rows.set(st["idx"], f"peak{int(k)}x_r", float(p[4] >= k * cost))


# ---------------------------------------------------------------- the select label book

class RealLabelPipe(SF.LabelPipe):
    """Y9's label book executed the way the live bot is: P_pool0 at entries 0 and 5 through realistic.RealExecutor at
    0.1 SOL (its own strategy names, `@y9real`, P_pool0's draws), the rug window from the drawn landing."""

    def __init__(self, eng, model: R.Model, name: str = "y9real"):
        super().__init__(eng, R.RealCosts(model=model), name=name, tag="y9real", executor=R.RealExecutor(model))
        self.model = model

    def signal(self, s, tok, t: float) -> None:
        n = len(self.rows)
        super().signal(s, tok, t)
        if len(self.rows) == n:
            return
        row = self.rows[-1]
        ws = self.rug.get(tok.mint) or []
        for w in [w for w in ws if w[0] is row]:             # the window from the signal: moved to the landing
            ws.remove(w)
        if not ws:
            self.rug.pop(tok.mint, None)
        land = t + self.model.fit.buy.quantile(R.u_of((s.p.get("base") or s.name, tok.mint, "buy")))
        self.eng.push(land, "pipe", (self, "_rug_start", (tok.mint, row)))

    def _rug_start(self, at: float, x) -> None:
        mint, row = x
        tok = self.eng.tokens.get(mint)
        price = C.price(tok.pq, tok.pb) if tok is not None and tok.pq and tok.pb else 0.0
        self.rug.setdefault(mint, []).append([row, price, at + SF.RUG_MS, price])
        self.eng.push(at + SF.RUG_MS, "pipe", (self, "_rug_end", (mint, row)))

    def _rug_end(self, at: float, data) -> None:
        mint, row = data
        ws = self.rug.get(mint) or []
        if any(w[0] is row and w[2] > at for w in ws):       # the signal's own end: the landing's window runs on
            return
        super()._rug_end(at, data)


# ---------------------------------------------------------------- the retrain's tables

def realistic_rows(table: dict) -> dict | None:
    """The decision rows with the realistic labels under the models' names, None when the rows have none yet."""
    if not any(c in table and bool((table[c] == table[c]).any()) for c in REAL_ROW.values()):
        return None
    out = dict(table)
    for k, c in REAL_ROW.items():
        out[k] = table[c]
    return out


def realistic_early(data: dict) -> dict | None:
    """The early tables with peak3x and peak10x at the realistic entry, None when the rows have none yet."""
    rows = data["rows"]
    if not any(c in rows and bool((rows[c] == rows[c]).any()) for c in REAL_EARLY.values()):
        return None
    return {**data, "rows": {**rows, **{k: rows[c] for k, c in REAL_EARLY.items()}}}


def costs_of(model: R.Model) -> R.RealCosts:
    """The realistic costs for exitpol's policy simulation (the hazard policy's k*)."""
    return R.RealCosts(model=model)


def until_day() -> str:
    return datetime.fromtimestamp(IDEAL_UNTIL_MS / 1000, timezone.utc).strftime("%Y-%m-%d")


def ideal_dir():
    """Where the old labels' twins go: no book reads this folder."""
    from .model import model_dir
    return model_dir() / "ideal"


def ideal_early(data: dict, log=print) -> dict:
    """X14's e_peak3x and e_peak10x (and Y10's et_ twins) on the old labels, with their purged walk-forward."""
    import numpy as np

    from . import early as E
    from . import exitpol as XP
    from . import model as M
    fr = XP.early_rows(data)
    feats = E.early_feature_list()
    models, evals = {}, {}
    for label in REAL_EARLY:
        m = np.isfinite(fr[label])
        sub = {k: v[m] for k, v in fr.items()}
        models["e_" + label] = M.fit(XP._x(sub, feats), sub[label], feats)
        if XP.has_trend(fr):
            models["et_" + label] = XP.fit_trend(fr, label)
        evals[label] = XP.evaluate_early(fr, label, feats)
    log(f"r2: the X14 _ideal twins {sorted(models)}")
    return {"models": models, "evals": evals}


def early_md(res: dict, twins: dict, realistic: bool) -> str:
    """The X14 report's R2 part: which labels, and the old labels' twins next to them."""
    def auc(ev):
        x = ((ev or {}).get("pooled") or {}).get("gbm") or {}
        return "n/a" if x.get("auc") is None else f"{x['auc']:.3f}"

    def rate(ev):
        r = (ev or {}).get("rate")
        return "n/a" if r is None else f"{r * 100:.1f} %"
    md = ["", "## R2: the labels", "",
          ("peak3x and peak10x at the realistic entry (labels_r2.py), the exits simulated at the realistic sale "
           "latency and fees; mig1h, alive5m and the step labels have no execution in them." if realistic else
           "The rows have no realistic labels yet (written before R2): the old ones.")]
    if twins:
        md += ["", f"Against the old labels (`e_<label>_ideal`, models/pumpfun_rt/ideal/, until {until_day()}):", "",
               "| label | rate realistic | rate old | AUC realistic | AUC old |", "|---|---|---|---|---|"]
        for k, ev in twins["evals"].items():
            r = (res.get("early") or {}).get(k)
            md.append(f"| {k} | {rate(r)} | {rate(ev)} | {auc(r)} | {auc(ev)} |")
    return "\n".join(md) + "\n"
