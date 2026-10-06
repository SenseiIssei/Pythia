# Pythia-Net (M3)

Our own sequence model for crypto, trained on the PC's RTX 4080. A small
PatchTST-style transformer: pretrained self-supervised on 14-day hourly
windows of every USDT pair Binance ever listed, then fine-tuned per quarter
to rank coins by next-week return and to forecast next-week volatility.

It is judged exactly like M2 (`research/lab/lab/experiments/picks.py`), on
the same days, and only earns a place in the engine if it beats it. See the
"Eigene KI-Modelle" section of the masterplan for where it fits.

## Setup (once)

The environment lives outside the repo, next to the synced data:

```bash
uv venv --python 3.12 F:/PythiaData/venv-net
```

```bash
uv pip install --python F:/PythiaData/venv-net/Scripts/python.exe torch --index-url https://download.pytorch.org/whl/cu128
```

```bash
uv pip install --python F:/PythiaData/venv-net/Scripts/python.exe polars pyarrow numpy scipy
```

## Run

The hourly bars come from the VPS (`python -m recorder.backfill --only
klines_1h_all`) through the normal sync to `F:/PythiaData`.

```bash
F:/PythiaData/venv-net/Scripts/python.exe research/net/pythia_net.py --data F:/PythiaData
```

A quick smoke test on 40 coins: add `--max-coins 40 --pretrain-epochs 1 --finetune-epochs 1`.

The report lands in `F:/PythiaData/reports/pythia_net/latest.md`.
