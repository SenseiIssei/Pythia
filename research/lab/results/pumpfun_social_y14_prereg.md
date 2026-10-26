# The coins' social links as features (Y14): pre-registration (2026-10-26)

Written and committed before any replay below was computed on data with the links (there is none yet: the record has
no metadata at all, the fetch was off). Code: `lab/pumpfun_rt/collector.py` (`meta_url`, `meta_flags`, `meta_social`,
`x_link`, `tg_handle`, `web_domain`), `lab/pumpfun_rt/store.py` (the columns of the table `meta`),
`lab/pumpfun_rt/socialfeat.py` (the features and the warm-up), `lab/pumpfun_rt/sim.py` (`Engine(social=...)`),
`lab/pumpfun_rt/pipeline.py` (`_build_y14`, `SOCIAL_RULE`, the filter key `social`, `Pipeline.social_ok`), the social
columns of the Y9 label rows (`selfeat.py`) and of X14's early rows (`early.py`), the twins (`selmodel.py`: `win0s`,
`rug0s`, `win5s`, `rug5s`; `exitpol.py`: `es_<label>`), the daily study and retrain (`study.py`, `retrain.py` through
`selmodel.train` and `exitpol.fit_live`), the paper engine (`live.py`), the run `lab/pumpfun_rt/social14.py`; tests
`tests/test_pumpfun_social_y14.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything; the
live service, its executor and its sizing are not touched (the live service builds its engine without the social
tracker and does not fetch metadata). A change to anything below after the first result is a new trial with a new
name.

## Why

The owner wants X (Twitter) used for earlier and better predictions. Reading X itself costs money (decided later).
What is free: the links a coin's creator puts into its metadata file. The collector fetched that file and kept only
flags; the fetch had been off since 2026-10-20 because ipfs.io and dweb.link answer 429. Y14 keeps the links,
normalised, and asks: (a) do features built on them make the win and rug models better out of sample; (b) do the paper
books built on them beat the same books without them.

## What was looked at before this plan

Disclosed: the collector's code and heartbeat (metadata off, no table `meta` in the record); a probe of the public
gateways on 2026-10-26 with one recent uri (ipfs.io and dweb.link 429, w3s.link and nftstorage.link redirect to them,
gateway.pinata.cloud 200) and then 7 recent pump.fun uris through gateway.pinata.cloud (7 of 7 answered; one document
read: an X link to a single tweet, a linktr.ee website); of the last creations about two thirds had an ipfs.io uri and
a third a launch tool's own host (not fetched). Y10's report and pre-registration. The code change was checked on
synthetic records in the tests and by replaying every rule and every strategy before Y14, in one shared paper book with
the label book, on the recorded 2026-10-20 without the social tracker and with it and the Y14 books (the server's
models): only the equality was looked at (section 8). No feature, label, model or book below was computed on the record.

## 1. The links (the table `meta`, nothing else of the document is kept)

Fetched as before: once per coin, at most 1 a second, 64 KB, 10 s, no redirect, only from public IPFS or Arweave
gateways; an IPFS uri (ipfs://, a gateway's /ipfs/<cid>, <cid>.ipfs.<gateway>) is fetched from gateway.pinata.cloud.
The fetch is on by default from the deploy (`PYTHIA_PF_META=0` turns it off). Kept next to the flags:

- `x_kind`: profile (x.com/<handle>, twitter.com/<handle>, @handle or a bare handle), status (x.com/<handle>/status/<id>,
  x.com/i/status/<id>), community (x.com/i/communities/<id>), search (x.com/search, x.com/hashtag), none (no X link),
  other (anything else, another site too)
- `x_handle` in lower case, `x_tweet` the tweet id (digits) when there is one
- `tg_handle`: the public telegram handle in lower case (t.me/<handle>, t.me/s/<handle>, @handle); none for an invite
  link
- `web_domain`: the website's registrable domain in lower case (the host's last two labels, three under a two-level
  suffix such as co.uk); none for an IP address, X, telegram or pump.fun

## 2. The features (`socialfeat.SOCIAL_FEATURES`, what the engine knows at t)

A coin counts for another only once its metadata was received, only when it was created strictly before the coin
scored, and as migrated only when its migration came before t. The tracker is warmed on the record's days before the
replay (`socialfeat.warm`; the paper engine on its last 14 days at start) and forgets coins created more than 14 days
before.

- `soc_known` 1 with the coin's metadata at t, else 0 (every other feature NaN then); NaN in rows without the tracker
- `soc_x_kind` (0 none, 1 profile, 2 status, 3 community, 4 search, 5 other)
- `soc_handle_prev`, `soc_tweet_prev`, `soc_tg_prev`, `soc_dom_prev`: earlier coins with the same X handle, tweet id,
  telegram handle, domain (0 when the coin has none); `soc_<key>_mig` how many of them migrated
- `soc_creator_handle`: the creator's earlier coins with the same X handle
- `soc_handle_is_name`: the X handle equals the coin's symbol or name (letters and digits, lower case)
- `soc_burst10`, `soc_burst60`: coins created in the 10 and 60 minutes before this one with the same tweet id or the
  same X handle, each coin once

## 3. The models

The same labels, rows, embargo and parameters as Y10's twins, with the social features added to Y10's features:
`sel_win0s`, `sel_rug0s`, `sel_win5s`, `sel_rug5s` (`selmodel.features_for`) and `es_<label>` for every early label
(`exitpol.social_features`). They train only on the rows written with the social tracker (`soc_known` not NaN), and
only once 200 or more rows have the coin's metadata (`has_social`); until then no model and the book skips "no model".
The daily retrain trains them with the others; every older model stays as it is.

## 4. The books (`pipeline._build_y14`, 0.1 SOL each, P_pool0's exits: +30 %, stop -20 %, 300 s)

- **B1** `P_pool5_top30s`: Y10's A2 (`P_pool5_top30t`) on `sel_win5s`: PumpSwap 5 s after the migration where P(win)
  is in its top 30 %.
- **B2** `P_pool0_wait_social`: `P_pool0_wait`, skipping a coin whose metadata is not known at the entry ("no social
  data") and a coin `SOCIAL_RULE` names ("social rule"): its X handle, telegram handle or domain was used by 2 or more
  earlier coins none of which migrated; or its creator used its X handle before; or 10 or more coins pointed at its
  tweet or handle in the 10 minutes before it.

## 5. The run (`social14.py`) and the rule

One replay with the trend and the social tracker, the label book and the early rows (no paths); at the end of every
UTC day the select models are trained on what was decided and labelled before the next day and used through it. The
books, each its own book of at most 4 positions under the daily loss limits of 0.25 SOL and 1.0 SOL, at Y9's measured
latency: W0 `P_pool0_wait`, S4 `P_pool5_top30`, A2 `P_pool5_top30t`, B1, B2. Out of sample from the first day with
both `win5t` and `win5s`. The window: the last 14 days up to the cutoff, the end of the 7th full UTC day after the
first day with the links (`social14.cutoff_ms`); `python -m lab.pumpfun_rt.social14` refuses before it and runs once
after it.

- (b) A book is better when, under both limits, the hour-paired band of the difference of the mean returns is above
  zero and its total P&L higher (Y9's rule): B1 against A2, B2 against W0.
- (a) A Y14 model improves on its Y10 twin when, walk-forward by day on the same rows (those with the social tracker),
  its AUC is at least 0.02 higher and its Brier skill not lower: `win0s` on `win0t`, `rug0s` on `rug0t`, `win5s` on
  `win5t`, `rug5s` on `rug5t`. `es_alive5m` and `es_peak3x` against `et_` by X14's purged walk-forward: reported, not
  judged.

## 6. Trials

2 books x 2 limits = 4 (`strategies.SOCIAL_Y14_TRIALS`).

## 7. How many days

The label book has about 170 to 190 migrations a day per entry (Y10); with metadata for about two thirds of the coins
(the other third points at a launch tool's host) the twins reach 200 rows with metadata after about 2 days, and the
deflated probability needs 5 days out of sample: 7 full days after the deploy's first day. The daily retrain trains the
twins by itself once the rows are there; B2 trades from the deploy on (no model needed), B1 from the first retrain with
`sel_win5s`.

## 8. Every earlier book trades as before

The recorded 2026-10-20 replayed with every rule and every strategy before Y14 without the social tracker, and with it
and the two Y14 books next to them (`python -m lab.pumpfun_rt.social14 --same 2026-10-20`): the closed trades, failed
buys and skip counts of the old ones compared field by field: 18,956 closed trades and 1,060 failed buys identical
field for field (the pid aside), the skip counts too (the day has no metadata, so this shows the tracker and the new
books change nothing next to them); and the synthetic record with metadata rows in the tests (also the label rows' old
columns). The live service is not changed.
