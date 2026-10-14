# Alerts and the daily digest

Pythia tells the owner, without opening the app, whether money is being made
and when something is wrong. Everything goes to one webhook: a Discord channel
webhook, a Slack incoming webhook, or anything else that takes the same JSON.

| Who posts | When | What |
|---|---|---|
| the engine (`pythia-server`) | as it happens | the operator alerts below |
| `lab.ops.notify` | every morning, after the learning loop | the daily digest |
| `system_health.sh` (via `notify.py --health`) | hourly, only on a change | health check not ok for two runs in a row, and green again |

Nothing is posted unless `PYTHIA_ALERT_WEBHOOK` is set. The webhook URL is a
secret: it is read from the environment only, never logged, never written to a
file Pythia owns, and an error says only the kind of failure (`HTTP 500`,
`not delivered (ConnectionRefusedError)`), never the URL.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `PYTHIA_ALERT_WEBHOOK` | unset (off) | where to POST |
| `PYTHIA_ALERT_FORMAT` | `discord` | `discord` posts `{"content": "..."}`, `slack` posts `{"text": "..."}` |
| `PYTHIA_ALERT_PREFIX` | `Pythia` | first word of every post, to tell several engines apart in one channel |
| `PYTHIA_ALERT_REJECTS` | `3` | engine: more than this many demo or live orders refused in a row is an alert |
| `PYTHIA_ALERT_DEDUP_MIN` | `30` | engine: the same alert is sent at most once in this many minutes |
| `PYTHIA_ALERT_MAX_PER_HOUR` | `20` | engine: posts per rolling hour; the rest are counted and the count rides on the next post |

`PYTHIA_ALERT_WEBHOOK` is separate from the older `PYTHIA_WEBHOOK_URL`, which
still mirrors every fill, exit and risk line of the journal. Set one, the
other or both.

## Engine alerts

| Alert | Sent when |
|---|---|
| Autopilot started | an autopilot is started, with its mode, venue, capital, rules and books |
| Autopilot stopped | stopped by hand, with its equity, P&L, trades and fees |
| Stop rule hit | take profit (stop) or its end time ended it |
| Floor hit | max loss, max loss in $, trailing floor or locked-in profit floor |
| Kill switch | engaged or released by hand, or tripped by the drawdown brake |
| Daily loss brake | the day's loss reached `maxDailyLossPct`; once per UTC day |
| Orders refused | more than `PYTHIA_ALERT_REJECTS` demo (or live) orders refused in a row, by the venue or before they got there; once per streak, a fill ends the streak; a dry run does not count |
| Reconcile mismatch | a venue reconcile corrected Pythia's book, or the Alpaca paper account and the demo book differ |
| Market data stale | quotes or candles stale for more than 10 minutes; once per episode, and once when fresh again |
| Model drift | a shadow model (the volatility model or the M2 ranking) has inputs outside its trained range: muted, its forecasts not to be trusted until back in range or retrained; once when it starts, once when it ends (checked every 5 minutes) |

How it is sent: the engine only queues an alert; a background task posts it.
The queue between them is bounded (64), so a slow or dead webhook never holds
up a tick: when the queue is full, new alerts are dropped and that is logged
once. Alerts arriving within two seconds of each other go out as one post.
The same alert (same key) is sent once per dedup window. A failing webhook is
logged once, and once more when it works again.

## Daily digest

`python -m lab.ops.notify` reads `reports/learn/latest.json`,
`reports/forward/latest.json` and `_health/system.json` and posts, in under
1800 characters:

- each running autopilot: equity, plus or minus today and since start in $
  and %, against BTC, trades and fees today (from the day before's digest; the
  first digest gives the totals since start and says so)
- the forward test status of every paper book
- anything red in the last health check, and a health check that has not run
  for more than two hours
- the learning loop's headline, and a warning when its report is not today's

Without a webhook it prints the digest and posts nothing; `--dry-run` does the
same with one set. It keeps its own snapshot in `<data>/notify/state.json`,
written only after a post went through.

## Health alarm

`notify.py --health <system.json>` is run by `system_health.sh` after each
hourly check. One run not ok stays quiet (a container restarting at that
moment); two in a row post once with every red check; the next all-green run
posts once that it is green again. The same `system.json` read twice counts as
one run. A post that fails is tried again on the next run. Its state is
`_health/alert_state.json`.

## Install

See `research/ops/README.md`, section "Alerts and the daily digest", for the
env file, the copy of `notify.py` and the cron line.
