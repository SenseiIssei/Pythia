# Alerts and the daily digest

Pythia tells the owner, without opening the app, whether money is being made
and when something is wrong. Everything goes to one webhook: a Discord channel
webhook, a Slack incoming webhook, or anything else that takes the same JSON.

| Who posts | When | What |
|---|---|---|
| the engine (`pythia-server`) | as it happens | the operator alerts below |
| `lab.ops.notify` | every morning, after the learning loop | the daily digest |
| `system_health.sh` (via `notify.py --health`) | hourly, only on a change | health check not ok for two runs in a row, and green again |
| `lab.ops.trending` | every 15 minutes; digest at the first run from 08:00 UTC | a strong volume surge on a coin Alpaca lists (watch only, once per coin per 20 h), and a daily watchlist: Alpaca coins' volume ratios, Binance gainers, on-chain hype labelled high risk (see `research/ops/README.md`, Trending watcher) |

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

Every digest except a dry run is written to `reports/notify/latest.json` as
`{"ts": <epoch ms>, "text": "...", "delivered": true}` (`delivered` false when
the post failed or no webhook is set), which the engine shows as `lastDigest`.

`notify.py --pending` sends a digest only when `reports/notify/request.json`
(written by `POST /api/alerts/digest`) is newer than the last digest; one
request gets one digest, delivered or not. A digest on demand does not move
the snapshot, so the next morning's digest still counts today's trades and
fees from the morning before. It is stdlib only and runs on the host every
five minutes, see the install section.

## Health alarm

`notify.py --health <system.json>` is run by `system_health.sh` after each
hourly check. One run not ok stays quiet (a container restarting at that
moment); two in a row post once with every red check; the next all-green run
posts once that it is green again. The same `system.json` read twice counts as
one run. A post that fails is tried again on the next run. Its state is
`_health/alert_state.json`.

## HTTP API

The engine (`pythia-server`) reports its alerts over HTTP so a dashboard can
show them. The API is generic and self-contained: plain JSON, no state outside
the engine and the lab's report folder. Like the rest of the engine's API it
has no authentication of its own, so the port stays private: publish it on
127.0.0.1 only (`-p 127.0.0.1:8787:8787`, or `PYTHIA_BIND=127.0.0.1:8787`
outside a container) and put anything that reaches it from outside behind
its own access control. Nothing in a response carries the webhook URL, the
bot token or the chat id; an error says only the kind of failure.

| Method and path | Does |
|---|---|
| `GET /api/alerts` | destination, mute, today's counts, the last 100 posts, the last digest |
| `POST /api/alerts/test` | sends one test message now |
| `POST /api/alerts/mute` | mutes for `{minutes}`; 0 unmutes |
| `POST /api/alerts/digest` | asks the lab for a digest now |

### GET /api/alerts

```json
{
  "enabled": true,
  "destination": "telegram",
  "mutedUntilMs": 0,
  "counts": { "sentToday": 3, "failedToday": 1, "suppressedToday": 2 },
  "recent": [
    {
      "ts": 1760450400000,
      "kinds": ["dataStale"],
      "text": "Pythia\nMarket data stale: quotes stale for 11 min",
      "delivered": false,
      "error": null,
      "reason": "muted"
    },
    {
      "ts": 1760446800000,
      "kinds": ["killSwitch", "floorHit"],
      "text": "Pythia\nKill switch: engaged by you\nFloor hit: Momentum stopped at its floor",
      "delivered": true,
      "error": null
    },
    {
      "ts": 1760443200000,
      "kinds": ["test"],
      "text": "Pythia\nTest: test message from the engine: alerts reach this destination.",
      "delivered": false,
      "error": "HTTP 401"
    }
  ],
  "lastDigest": { "ts": 1760424600000, "text": "Pythia daily 2026-10-14\n..." }
}
```

- `enabled` false and `destination` null: no destination is configured
  (neither `PYTHIA_ALERT_WEBHOOK` nor the two Telegram variables).
  `destination` is `discord`, `slack` or `telegram`.
- `mutedUntilMs`: epoch ms, 0 when not muted.
- `counts` are for the current UTC day: `sentToday` posts that went through,
  `failedToday` posts the destination did not take, `suppressedToday` events
  held back by the mute or the hourly limit. Repeats dropped by the dedup
  window are not counted.
- `recent`: newest first, at most 100, kept in memory (a restart starts it
  empty). One entry per post; events held back are one entry per batch with
  `delivered` false, `error` null and `reason` `muted` or `hourlyLimit`.
  `kinds` are `autopilotStarted`, `autopilotStopped`, `stopRuleHit`,
  `floorHit`, `killSwitch`, `dailyLossBrake`, `orderRejects`,
  `reconcileMismatch`, `dataStale`, `modelDrift` and `test`.
- `lastDigest`: `ts` and `text` of `reports/notify/latest.json` under
  `PYTHIA_DATA`, null when there is none yet.

### POST /api/alerts/test

No body. Posts one test message through the configured destination right
away, past the queue, the dedup window, the hourly limit and the mute, and
records it in `recent`.

- `200` it went through: `{"ts": 1760443200000, "kinds": ["test"], "text": "...", "delivered": true, "error": null}`
- `502` the destination did not take it: the same record with `delivered`
  false and `error` such as `"HTTP 401"`
- `409` alerts are not configured:
  `{"error": "alerts are not configured: set PYTHIA_ALERT_WEBHOOK (Discord or Slack), or PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID, and restart the server"}`

### POST /api/alerts/mute

```json
{ "minutes": 120 }
```

Answers `200 {"mutedUntilMs": 1760457600000}`; `{"minutes": 0}` unmutes and
answers `{"mutedUntilMs": 0}`. At most 10080 minutes (seven days); more is
`400 {"error": "minutes must be 0 to 10080 (seven days)"}`, a negative or
missing number is a 4xx from the JSON parser.

While muted, events are recorded in `recent` with `delivered` false and
`reason` `muted`, and nothing is posted, except the kill switch and a floor
hit: those still go out, because they mean the money stopped trading. The
mute is saved in the engine state file (`PYTHIA_STATE_FILE`) at once, so it
holds across a restart; without a state file it lasts until the restart. A
mute can be set while alerts are off and applies once they are on. The test
message and the lab's digest and health alarm are not muted.

### POST /api/alerts/digest

No body. Writes `reports/notify/request.json` under `PYTHIA_DATA`
(`{"ts": 1760450400000, "source": "api"}`) and answers
`202 {"requestedAt": 1760450400000}`. The lab's `notify.py --pending`, run
every five minutes, sends a digest when that request is newer than the last
digest, so it arrives within about five minutes; its result shows up as
`lastDigest`. `409 {"error": "no data folder: set PYTHIA_DATA to the lab's data root"}`
when the engine has no data folder.

The engine needs the lab's `reports/notify` folder for `lastDigest` and the
request: give its container the data folder and `PYTHIA_DATA`, for example
`-v /srv/pythia-data/reports/notify:/data/reports/notify -e PYTHIA_DATA=/data`.
The lab writes there through `PYTHIA_REPORTS` when set, else
`<PYTHIA_DATA>/reports`; the two must point at the same folder.

## Install

See `research/ops/README.md`, section "Alerts and the daily digest", for the
env file, the copy of `notify.py` and the cron line.
