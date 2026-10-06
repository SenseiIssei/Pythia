"""Do M2 and Pythia-Net see different things? Their combination, out of sample.

Both write their out-of-sample scores (reports/picks/scores.parquet from the
VPS, reports/pythia_net/scores.parquet from the PC). On the days and coins
both scored, this measures how alike the two rankings are and the Rank-IC of
each, and of their average rank. If the average beats both, the two models
carry different information and the ensemble is the one to use.

    F:/PythiaData/venv-net/Scripts/python.exe research/net/ensemble.py --data F:/PythiaData
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import polars as pl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="F:/PythiaData")
    root = Path(ap.parse_args().data)
    m2 = pl.read_parquet(root / "reports" / "picks" / "scores.parquet").select("day", "symbol", m2="score", fwd="fwd")
    m3 = pl.read_parquet(root / "reports" / "pythia_net" / "scores.parquet").select("day", "symbol", m3="score")
    df = m2.join(m3, on=["day", "symbol"], how="inner").drop_nulls().filter(pl.col("fwd").is_not_nan())
    df = df.with_columns(
        r2=pl.col("m2").rank().over("day") / pl.len().over("day"),
        r3=pl.col("m3").rank().over("day") / pl.len().over("day"),
    ).with_columns(ens=(pl.col("r2") + pl.col("r3")) / 2)
    per_day = df.group_by("day").agg(
        n=pl.len(),
        alike=pl.corr("m2", "m3", method="spearman"),
        ic_m2=pl.corr("m2", "fwd", method="spearman"),
        ic_m3=pl.corr("m3", "fwd", method="spearman"),
        ic_ens=pl.corr("ens", "fwd", method="spearman"),
    ).filter(pl.col("n") >= 20)
    out = {c: float(per_day[c].drop_nans().mean()) for c in ("alike", "ic_m2", "ic_m3", "ic_ens")}
    t = {c: out[c] / (per_day[c].drop_nans().std() / np.sqrt(per_day.height)) for c in ("ic_m2", "ic_m3", "ic_ens")}
    lines = [
        f"{df.height:,} coin-days both models scored, {per_day.height} days.",
        f"How alike the rankings are (Spearman): {out['alike']:.2f}",
        f"Rank-IC  M2 {out['ic_m2']:.4f}   Pythia-Net {out['ic_m3']:.4f}   average {out['ic_ens']:.4f}",
        ("The average beats both: the models see different things, use the ensemble."
         if out["ic_ens"] > max(out["ic_m2"], out["ic_m3"]) else
         "The average does not beat the better model: keep the better one alone."),
    ]
    text = "# M2 and Pythia-Net combined\n\n" + "\n\n".join(lines) + "\n"
    d = root / "reports" / "ensemble"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
