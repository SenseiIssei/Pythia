# The coins' social links as features (Y14)

PAPER ONLY. Pre-registration: `results/pumpfun_social_y14_prereg.md` (4 trials). Code: `collector.py` (the links,
normalised), `socialfeat.py` (the features), `selmodel.py` and `exitpol.py` (the twins), `pipeline._build_y14` (the
books), `social14.py` (the run); tests `tests/test_pumpfun_social_y14.py`.

## Short answer

**Not answerable yet: the record has no metadata.** The fetch had been off since 2026-10-20 (ipfs.io and dweb.link
answer 429); it is on again from this deploy, through gateway.pinata.cloud (7 of 7 recent uris answered on 2026-10-26),
and keeps only the flags and the normalised links (X link kind, X handle, tweet id, telegram handle, website domain).

- From the deploy: the paper engine, the daily study and the retrain carry the social tracker; `P_pool0_wait_social`
  (B2) trades on paper at once, `P_pool5_top30s` (B1) and the twins `sel_win0s`, `sel_rug0s`, `sel_win5s`, `sel_rug5s`,
  `es_<label>` once 200 label rows have the coin's metadata (about 2 days). Every older model stays as it is.
- The registered evaluation needs 7 full UTC days after the deploy's first day (2 to train, 5 out of sample):
  `python -m lab.pumpfun_rt.social14` (it refuses before), then this file gets the answer.
- Every earlier book trades exactly as before: the recorded 2026-10-20 replayed with every rule and strategy before Y14
  without and with the social tracker and the Y14 books gives the same 18,956 closed trades and 1,060 failed buys,
  field for field, and the same skips (`social14 --same 2026-10-20`); the live service is not touched.
