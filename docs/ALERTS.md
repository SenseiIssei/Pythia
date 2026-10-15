# Alerts, the daily digest and the weekly report

Pythia tells the owner on the phone, without opening the app, whether money
is being made and when something is wrong. Everything goes to one Telegram
chat (or, instead, a Discord or Slack webhook), in one design.

| Who posts | When | What |
|---|---|---|
| the engine (`pythia-server`) | as it happens | autopilot events, trades and rebalances, big moves, risk, venue and data problems, model drift |
| a lab job, through `POST /api/alerts/event` or `lab.ops.notify` | as it happens | studies and the factory, listings, trending, CS2, Pokemon, model promotions |
| `lab.ops.notify` | every morning, after the learning loop | the daily digest with its chart |
| `lab.ops.notify --weekly` | Sunday 18:00 Europe/Berlin | the weekly report with its chart |
| `notify.py --health` (from `system_health.sh`) | hourly, only on a change | health check red for two runs in a row, and green again |

## What a message looks like

Every message is a card: a bold title with one leading emoji, one short
summary line, the key numbers aligned in a monospace block (signs, thousands
separators, %, a green or red circle for plus or minus), and an optional
footer in italics with the engine's name. No walls of text: a long post is
fitted to Telegram's limit by shortening its tables ("+12 more") and leaving
whole cards out ("+3 more in the app"), never by cutting it in the middle.

An autopilot stopped by its floor:

```
🛑 Momentum stopped
Max loss reached.
Equity            $9,412.30
P&L       -$587.70 -5.88 % 🔴
vs BTC          -4.10 pts 🔴
Trades                   14
Fees                 $11.20
Closed its 3 position(s). · Pythia
```

The fills of one rebalance, as one message with a small table:

```
🔁 Rebalance · Momentum
3 trades: bought $1,220.00, sold $1,500.00.
Side Coin  Value      Price
Sell ETH  $1,500  $3,000.00
Buy  BTC  $1,220 $61,000.00
Buy  SOL    $410    $151.30
Realised  +$5.00 🟢
Fees       $0.30
Demo: virtual money at the venue · Pythia
```

The daily digest (with the chart as a photo, this text as its caption):

```
📊 Daily · Wed 14 Oct
1 autopilot running, +$10.20 today 🟢 · BTC +0.50 %
Momentum · demo
Equity              $1,030.00
Today         +$10.20 +1.00 % 🟢
Since start   +$30.00 +3.00 % 🟢
vs BTC              +1.50 pts 🟢
BTC                   +1.50 %
Trades today   3 · fees $1.25
Forward test tsmom ✅ on track · m4_ls 👀 watch · picks_ls 🌱 early
Health ✅ all green
Learning 2 cost updates; 1 autopilot running, best +1.50 points against BTC since start.
Pythia
```

On Telegram the title is bold, the numbers are in a `<pre>` block and the
footer is in italics: posts go with `parse_mode: HTML`, and every piece of text
in them is escaped (`&`, `<`, `>`), so a coin or strategy name can never break
the markup. Should Telegram still refuse a post's HTML, the same text goes out
once more as plain text. Discord gets the same card in its markdown (`**bold**`,
a code block), Slack in its own (`*bold*`, a code block).

### Charts

The daily digest and the weekly report come with one PNG (1200 x 1440 px,
drawn by `lab.ops.charts` with matplotlib) in the app's light look: white
background, near-black ink, one blue accent, green and red only for gains and
losses.

- top: each running autopilot's equity in % (since its start for the digest,
  over the week for the report) against BTC bought and held over the same
  span (dashed grey), with the last value at the end of each line
- bottom left: P&L per sleeve, green bars up, red bars down
- bottom right: what the autopilots hold, by value, with its share

It goes as a Telegram photo (`sendPhoto`) whose caption is the card in HTML.
When the card does not fit a caption (1024 characters), the photo carries the
title and summary and the full card follows as a message. The data comes from
every autopilot engine's `GET /api/state` (`PYTHIA_AUTOPILOT_STATE_URLS`, the
main and the safe account, each autopilot labelled with its account) and BTC
prices from Binance's public klines; without either, or without matplotlib, the
digest goes out as text.

## Categories

Every alert has a category with a switch in the app (Notifications, "What is
sent"). All are on by default.

| Id | Switch | Sent by | What |
|---|---|---|---|
| `trades` | Trades | engine | each fill of an autopilot outside a lab rebalance; fills that arrive together go out as one message |
| `rebalances` | Rebalances | engine | the fills of one lab-book rebalance, one message with a table (side, coin, value, price), realised P&L and fees |
| `dailyPnl` | Daily P&L | lab | the morning digest with its chart |
| `bigMoves` | Big moves | engine | a coin an autopilot holds, or an autopilot's equity, moving more than the set % within an hour or a day |
| `autopilot` | Autopilot events | engine | an autopilot started, stopped, or ended by take profit or its end time |
| `risk` | Risk | engine | floor hit, kill switch, daily loss brake, orders refused again and again |
| `venue` | Venue and data problems | engine and lab | reconcile mismatch, market data stale, the hourly health check |
| `models` | Models | engine and lab | a model muted by drift and back in range, a retrain or promotion |
| `studies` | Studies and factory | lab | study and strategy factory results |
| `listings` | Listings | lab | new coins listed on a venue |
| `trending` | Trending | lab | volume surges on coins Alpaca lists, and the daily watchlist |
| `cs2` | CS2 | lab | CS2 skin market findings |
| `pokemon` | Pokemon | lab | Pokemon card market findings |
| `weekly` | Weekly report | lab | Sunday 18:00: the week in one chart and a few numbers |

The kill switch, a floor hit and the daily loss brake are urgent: they go out
whatever the switches, the mute and quiet hours say, and past the hourly
limit, because they mean the money stopped trading or reached its daily loss
limit. So does an autopilot's equity moving twice the big-move size, and a lab
event posted with `"urgent": true`.

The test message (`POST /api/alerts/test`) and the morning note after quiet
hours have no category and always go out.

## Quiet hours

From 23:00 to 07:00 Europe/Berlin by default (summer and winter time alike),
only urgent alerts go out. The rest are recorded (`reason: "quiet"` in
`GET /api/alerts`) and listed in one message once quiet hours are over:

```
🌙 Quiet hours are over
2 alerts were held back from 23:00 to 07:00. Urgent ones went out at once.
Time  Alert
00:30 BTC +4.1 % in 1 h
03:40 Momentum stopped
Pythia
```

Start, end and time zone are set in the app (Notifications, Quiet hours) or
through `POST /api/alerts/settings`; they can be switched off. The lab follows
the same hours: a lab post in quiet hours is held in `reports/notify/held.json`
and listed by the next `notify.py --pending` after them; a daily digest that
falls into quiet hours is sent by `--pending` once they end, and still counts
as the day's digest; the health alarm waits for the first bad run after them.
`PYTHIA_QUIET_HOURS` (`off`, or `23:00-07:00`) overrides the hours for a lab
job.

## Big moves

The engine samples every minute each active autopilot's equity and the price
of every coin they hold, and compares it with an hour and 24 hours before.
Past the set size (3 % in an hour and 8 % in a day by default, set in the app
or with `bigMoves` in `POST /api/alerts/settings`):

```
📈 BTC +4.2 % in 1 h
Held by Momentum.
Now        $67,234.10
1 h ago    $64,524.00
Change        +4.20 % 🟢
Pythia
```

A move counts only once that much history exists, so a restart never reads
its first minutes as a move. The same move is said once per window, and again
only when it grew by another full threshold.

## How the engine sends

The engine only queues an alert; a background task posts it. The queue
between them is bounded (256), so a slow or dead destination never holds up a
tick: when the queue is full, new alerts are dropped and that is logged once.
Alerts arriving within two seconds of each other go out as one post (one card
each, the fills of one autopilot in one table). The same alert (same key) is
sent once per dedup window (30 minutes). At most 20 posts per rolling hour; the
rest are recorded with `reason: "hourlyLimit"` and counted on the next post,
urgent ones pass. A failing destination is logged once, and once more when it
works again.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `PYTHIA_TELEGRAM_BOT_TOKEN` | unset | the bot's token (from BotFather) |
| `PYTHIA_TELEGRAM_CHAT_ID` | unset | the owner's chat with the bot; both are needed |
| `PYTHIA_ALERT_WEBHOOK` | unset | instead of Telegram: a Discord or Slack webhook; wins when set |
| `PYTHIA_ALERT_FORMAT` | `discord` | with a webhook: `discord` posts `{"content"}`, `slack` posts `{"text"}` |
| `PYTHIA_ALERT_PREFIX` | `Pythia` | the footer of every post, to tell several engines apart in one chat |
| `PYTHIA_ALERT_REJECTS` | `3` | engine: more than this many demo or live orders refused in a row is an alert |
| `PYTHIA_ALERT_DEDUP_MIN` | `30` | engine: the same alert is sent at most once in this many minutes |
| `PYTHIA_ALERT_MAX_PER_HOUR` | `20` | engine: posts per rolling hour; urgent ones pass |
| `PYTHIA_ALERT_EVENT_FROM` | unset | engine: besides 127.0.0.1 and ::1, who may post events: addresses or prefixes ending in `.` (`172.17.` for a Docker bridge), comma separated |
| `PYTHIA_ALERT_IMAGE_DIR` | unset | engine: a folder an event's image may come from, besides `PYTHIA_DATA` |
| `PYTHIA_QUIET_HOURS` | unset | lab: `off`, or `HH:MM-HH:MM`, over the settings file |
| `PYTHIA_ALERT_VIA` | unset | lab: `engine` posts lab cards through `POST /api/alerts/event` |
| `PYTHIA_ALERT_EVENT_URL` | from the state URL | lab: where that endpoint is |
| `PYTHIA_AUTOPILOT_STATE_URLS` | `http://127.0.0.1:8788/api/state,http://127.0.0.1:8789/api/state` | lab: every autopilot engine (main and safe Alpaca paper account), comma separated; `?name=` names an account, else main, safe by place; one that does not answer is skipped |
| `PYTHIA_AUTOPILOT_STATE_URL` | unset | lab: the old single engine, read only when the list is unset; `off` for none |

The category switches, quiet hours and big-move sizes are saved with the
engine state (`PYTHIA_STATE_FILE`) and written for the lab to
`reports/notify/settings.json` under `PYTHIA_DATA` at start and on every
change.

The bot token and the webhook URL are secrets: read from the environment only,
never logged, never written to a file Pythia owns, and an error says only the
kind of failure (`HTTP 500`, `not delivered (ConnectionRefusedError)`), never
the URL, the token or the chat id.

`PYTHIA_ALERT_WEBHOOK` is separate from the older `PYTHIA_WEBHOOK_URL`, which
still mirrors every fill, exit and risk line of the journal as plain text.

## Engine alerts

| Alert | Category | Sent when |
|---|---|---|
| Autopilot started | autopilot | an autopilot is started: capital, mode, venue, books, its rules in one line |
| Autopilot stopped | autopilot | stopped by hand: equity, P&L, against BTC, trades and fees |
| Stop rule hit | autopilot | take profit (stop) or its end time ended it |
| Floor hit | risk, urgent | max loss, max loss in $, trailing floor or locked-in profit floor |
| Kill switch | risk, urgent | engaged or released by hand, or tripped by the drawdown brake |
| Daily loss brake | risk, urgent | the day's loss reached `maxDailyLossPct`; once per UTC day |
| Orders refused | risk | more than `PYTHIA_ALERT_REJECTS` demo (or live) orders refused in a row; once per streak |
| Reconcile mismatch | venue | a venue reconcile corrected Pythia's book, or the Alpaca paper account and the demo book differ |
| Market data stale | venue | quotes or candles stale for more than 10 minutes; once per episode, and once when fresh again |
| Model drift | models | a shadow model has inputs outside its trained range; once when it starts, once when it ends |
| Trade | trades or rebalances | a fill of an autopilot (paper, demo or live); a lab book's fills count as a rebalance |
| Big move | bigMoves | see Big moves |

## Daily digest

`python -m lab.ops.notify` reads `reports/learn/latest.json`,
`reports/forward/latest.json` and `_health/system.json`, and the engine's
`GET /api/state` for the chart, and posts:

- each running autopilot (at most six; the rest are counted): equity, today and
  since start in $ and %, against BTC, trades and fees today (from the day
  before's digest; the first digest gives the totals since start and says so)
- the forward test status of every paper book
- anything red in the last health check, and a check that has not run for
  more than two hours
- the learning loop's headline, and a warning when its report is not today's

Without a destination it prints the digest and posts nothing; `--dry-run` does
the same with one set. It keeps its own snapshot in `<data>/notify/state.json`,
written only after a post went through.

Every digest except a dry run is written to `reports/notify/latest.json` as
`{"ts", "text", "html", "delivered", "photo"}` (`text` without markup, `html` as
posted; `delivered` false when the post failed or no destination is set),
which the engine shows as `lastDigest`.

`notify.py --pending` (every five minutes) sends a digest when
`reports/notify/request.json` (written by `POST /api/alerts/digest`, or by a
digest held in quiet hours) is newer than the last digest; one request gets one
digest, delivered or not. A digest on demand does not move the snapshot. It
also sends the note on lab posts held in quiet hours, once they are over.

## Weekly report

`python -m lab.ops.notify --weekly` runs on Sunday afternoons and sends once a
week, from 18:00 Europe/Berlin (`--force`: now, whatever the day). For each
running autopilot: equity, the week and since start in $ and %, against BTC
over the week, how far below its peak, trades this week; the best and worst
sleeve; and the chart over the week. Its state (the week sent, the trade
counts) is in `<data>/notify/state.json`.

## Health alarm

`notify.py --health <system.json>` is run by `system_health.sh` after each
hourly check. One run not ok stays quiet (a container restarting at that
moment); two in a row post once with every red check; the next all-green run
posts once that it is green again. The same `system.json` read twice counts as
one run. A post that fails, or falls into quiet hours, is tried again on the
next bad run. Its state is `_health/alert_state.json`.

## HTTP API

The engine (`pythia-server`) reports its alerts over HTTP so a dashboard can
show them. Like the rest of the engine's API it has no authentication of its
own, so the port stays private: publish it on 127.0.0.1 only
(`-p 127.0.0.1:8787:8787`, or `PYTHIA_BIND=127.0.0.1:8787` outside a container)
and put anything that reaches it from outside behind its own access control.
Nothing in a response carries the webhook URL, the bot token or the chat id.

| Method and path | Does |
|---|---|
| `GET /api/alerts` | destination, mute, today's counts, the last 100 posts, the last digest |
| `POST /api/alerts/test` | sends one test card now |
| `POST /api/alerts/mute` | mutes for `{minutes}`; 0 unmutes |
| `POST /api/alerts/digest` | asks the lab for a digest now |
| `GET /api/alerts/settings` | the category switches, quiet hours, big-move sizes |
| `POST /api/alerts/settings` | changes them |
| `POST /api/alerts/event` | a lab job posts an alert (this machine only) |

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
      "kinds": ["bigMove"],
      "title": "BTC +4.2 % in 1 h",
      "text": "<b>📈 BTC +4.2 % in 1 h</b>\nHeld by Momentum.\n<pre>...</pre>\n<i>Pythia</i>",
      "delivered": false,
      "error": null,
      "reason": "quiet"
    },
    {
      "ts": 1760446800000,
      "kinds": ["trade", "trade", "trade"],
      "title": "Rebalance · Momentum",
      "text": "<b>🔁 Rebalance · Momentum</b>\n...",
      "delivered": true,
      "error": null
    },
    {
      "ts": 1760443200000,
      "kinds": ["event"],
      "title": "Week 42",
      "text": "<b>🗓️ Week 42</b>\n...",
      "delivered": true,
      "error": null,
      "photo": true
    }
  ],
  "lastDigest": { "ts": 1760424600000, "text": "📊 Daily · Wed 14 Oct\n..." }
}
```

- `enabled` false and `destination` null: no destination is configured.
  `destination` is `telegram`, `discord` or `slack`.
- `mutedUntilMs`: epoch ms, 0 when not muted.
- `counts` are for the current UTC day: `sentToday` posts that went through,
  `failedToday` posts the destination did not take, `suppressedToday` events
  held back by the mute, quiet hours or the hourly limit. Repeats dropped by
  the dedup window and alerts switched off are not counted.
- `recent`: newest first, at most 100, kept in memory (a restart starts it
  empty). One entry per post; events held back are one entry per batch with
  `delivered` false, `error` null and `reason` `muted`, `quiet` or
  `hourlyLimit`. `title` is the first card's title, `text` the post in the
  destination's markup, `photo` true when a chart went with it. `kinds` are
  `autopilotStarted`, `autopilotStopped`, `stopRuleHit`, `floorHit`,
  `killSwitch`, `dailyLossBrake`, `orderRejects`, `reconcileMismatch`,
  `dataStale`, `modelDrift`, `trade`, `bigMove`, `event`, `overnight` and
  `test`.
- `lastDigest`: `ts` and `text` of `reports/notify/latest.json` under
  `PYTHIA_DATA`, null when there is none yet.

### POST /api/alerts/test

No body. Posts one test card through the configured destination right away,
past the queue, the dedup window, the hourly limit, the mute and quiet hours,
and records it in `recent`. It shows the design and what is set:

```
✅ Test message
Alerts from the engine reach this chat.
Categories on               14 of 14
Quiet hours           23:00 to 07:00
Big move         3 % / 1 h, 8 % / 24 h
Example gain     +$1,234.50 +1.23 % 🟢
Example loss         -$87.65 -0.42 % 🔴
Pythia
```

- `200` it went through: `{"ts", "kinds": ["test"], "title": "Test message", "text", "delivered": true, "error": null}`
- `502` the destination did not take it: the same record with `delivered`
  false and `error` such as `"HTTP 401"`
- `409` alerts are not configured

### POST /api/alerts/mute

`{"minutes": 120}` answers `200 {"mutedUntilMs": 1760457600000}`;
`{"minutes": 0}` unmutes. At most 10080 minutes (seven days); more is `400`.
While muted, events are recorded with `reason` `muted` and nothing is posted
but the urgent ones. The mute is saved in the engine state file at once. The
test message and the lab's posts are not muted (they follow the switches and
quiet hours).

### POST /api/alerts/digest

No body. Writes `reports/notify/request.json` under `PYTHIA_DATA` and answers
`202 {"requestedAt": 1760450400000}`; the lab's `notify.py --pending` sends the
digest within about five minutes. `409` when the engine has no data folder.

### GET /api/alerts/settings

```json
{
  "categories": [
    { "id": "trades", "label": "Trades", "emoji": "💱", "about": "Each fill of an autopilot outside a rebalance.", "source": "engine", "on": true },
    { "id": "dailyPnl", "label": "Daily P&L", "emoji": "📊", "about": "The morning digest with the equity chart.", "source": "lab", "on": false }
  ],
  "quietHours": { "enabled": true, "start": "23:00", "end": "07:00", "timezone": "Europe/Berlin" },
  "bigMoves": { "hourPct": 3.0, "dayPct": 8.0 },
  "quietNow": false
}
```

All fourteen categories are listed, in the order of the table above.

### POST /api/alerts/settings

A change; what is left out stays:

```json
{ "categories": { "trades": false, "pokemon": false }, "quietHours": { "start": "22:30", "end": "06:30" }, "bigMoves": { "dayPct": 10 } }
```

Answers `200` with the settings as `GET` gives them, saved with the engine
state at once and written to `reports/notify/settings.json`. All or nothing:
an unknown category, a time that is not `HH:MM`, an unknown time zone, an
hour size outside 0.5 to 50 or a day size outside 1 to 90 is `400` with the
reason, and nothing changes. An unknown field is a `4xx` from the parser.

### POST /api/alerts/event

What a lab job posts, sent with the engine's card design, switches, quiet
hours, mute and limits:

```json
{
  "category": "studies",
  "title": "Factory 2026-10-17",
  "text": "3 new strategies survived the holdout.",
  "rows": [["Tried", "120"], { "label": "Best OOS Sharpe", "value": "+1.40", "sign": 1.4 }],
  "table": { "header": ["Name", "Sharpe"], "rows": [["tsmom_v2", "1.40"], ["carry", "0.90"]] },
  "footer": "results/factory.md",
  "image": "reports/notify/charts/factory.png",
  "urgent": false,
  "emoji": "🧪",
  "key": "factory:2026-10-17"
}
```

Only `category` and `title` are needed. A row is `[label, value]`, or an
object whose `sign` picks the green or red circle. `image` is a PNG or JPEG of
at most 10 MB inside `PYTHIA_DATA` (a relative path is taken from there) or
`PYTHIA_ALERT_IMAGE_DIR`; it goes as a Telegram photo with the card as its
caption. `key` deduplicates: the same key inside 30 minutes sends once.

- `202 {"queued": true, "quietNow": false}`: queued (`quietNow` true: it will
  wait for the end of quiet hours)
- `200 {"queued": false, "reason": "off"}`: its category is switched off
- `400` an unknown category (the answer lists them), an empty or longer than
  120 character title, more than 1500 characters of text, more than 20 rows
  or a table larger than 60 rows by 6 columns, or an image that is missing,
  outside those folders, too large or not a PNG or JPEG
- `403` from anywhere but 127.0.0.1, ::1 or `PYTHIA_ALERT_EVENT_FROM`
- `409` alerts are not configured

From the shell, through the lab instead of the engine:

```bash
python3 notify.py --event venue "Disk almost full" "12 GB left on /srv"
```

## Install

See `research/ops/README.md`, section "Alerts and the daily digest", for the
env file, the copy of `notify.py`, the lab image with matplotlib and the cron
lines.
