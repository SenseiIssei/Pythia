# pump.fun recorder: the creations still missing after C1, and the PumpSwap gaps since 2026-11-03

Pre-registration `results/pumpfun_creation_gap_prereg.md`. Read only: the lab's record `<data>/pumpfun_rt`, the job runs
`<data>/_ops/runs`; the one network read is the collector's own creation reader for the 111 coins below (2 calls a
second, the public RPC). Three trials in R5's registry, family pumpfun, counted only (`pumpfun:creation_gap:split`,
`:reread`, `:amm_gaps`). The first look at these counts came before the pre-registration (said there); the run
after it made them again, and they matched.

## 1. Creations, 2026-11-14

| migrated coins | creation from stream (creates, any day) | late only (creates_late, any day) | neither |
|---|---|---|---|
| 697 | 483 (69.3 %) | 103 (14.8 %) | 111 (15.9 %) |

coverage.md said 70.9 % for this day. It looked for creation rows only on the day and the two days before. But
creates_late is partitioned by the creation's block time, often months back (median 61 days, up to 511), so most
late rows fell outside that window, and so did stream rows of coins created more than two days before they
migrated. Counted on any day the share is 84.1 %. On 2026-11-15: 714 coins, 523 from stream, 47 late, 144 neither
(79.8 %).

Of the 111 with neither: every one had a completion or migration on record, so the read was asked for each (0 never
asked). 9 mints do not end in "pump". Reading them again with the collector's reader:

| outcome | coins |
|---|---|
| read now; C1's reader got -32015, "Transaction version (1) is not supported" (it asked with version 0) | 77 |
| read now; C1's reader would also have read it (failed then, and a failed read was never tried again) | 15 |
| the curve's oldest transaction holds no creation of this mint | 11 |
| HTTP 429 from the public RPC on this read | 8 |

12 of the coins read needed more than C1's 10 pages of 1,000 signatures. None needed more than 50.

Fix (lab collector only, the live service's subclass unchanged): getTransaction asks for version 1, the read pages
back up to 50, a failed read is tried again after 60 s, doubling each time, at most 4 times, and every outcome is
logged in `late_reads.jsonl`. coverage.md now shows from stream and late separately and groups the coins with
neither by their read's outcome. The check is red under 95 % on a full day from 2026-11-17. If this day's misses
had been read: 92 read now plus up to 8 rate-limited ones on retry gives (586 + 92 to 100) / 697 = 97.3 % to
98.4 %. What may remain: the 11 whose oldest transaction holds no creation (the record does not say why; the next
day's log names them), and curves with more than 50,000 signatures.

## 2. PumpSwap gaps

| | 2026-10-28 to 11-02 | 11-04 to 11-15 |
|---|---|---|
| PumpSwap gaps a day | 49 to 148 | 275 to 603 |
| time between gaps, median | 160 s (10-30) | 67 s (11-12) |
| Spearman by hour: gaps against PumpSwap rows, curve trades, job seconds, receive lag | -0.18, 0.11, -0.41, 0.20 | -0.20, 0.05, -0.15, -0.03 |

The jump came on 2026-11-03 from 18 UTC. Gaps cluster from 13 to 24 UTC. Few PumpSwap gaps overlap a pump.fun gap
(25 of 1,550 on 11-12 to 11-14) or a gap of the transfer link (137). They follow neither our load nor the lab's
jobs. Nothing in the repo changed the stream then: C1 came on 11-02 at 10:38, and the containers restarted on 11-03
at 15:07. The PumpSwap links are dropped more often by the public endpoint, a cause outside the repo. Two lab-side
amplifiers are fixed. With two links, both were down at once far more often than pump.fun's three (9 to 65 gaps a
day), so PumpSwap now has three links. And a link that lived under 60 s backed off up to 60 s even though it had
worked, so drop after drop kept both down. Now a link that carried notifications reconnects at once. The
collector's container logs are not readable from the lab. From the deploy on, every drop (reason, close code or
HTTP status, seconds up) goes to `links.jsonl`, and coverage.md counts the drops per program. If the gaps stay, the
fix is outside the repo: a paid provider (`PYTHIA_SOLANA_WS_URLS`) or a Geyser feed.
