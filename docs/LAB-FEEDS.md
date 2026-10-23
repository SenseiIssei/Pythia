# Lab feeds

Any lab job can show up in the app without touching the engine or the UI: it
writes one JSON file, and the Research page and the Home insights pick it up on
their next refresh.

## Where

```
<PYTHIA_DATA>/reports/<name>/latest.json
```

`<name>` is the job's folder name (`listings`, `trending`, `cs2`, `models`,
...). Folders starting with `_` or `.` are private to the lab and skipped.
`report.write(name, markdown, data)` in `research/lab/lab/report.py` already
writes this file; dated copies next to it are ignored by the app.

The engine serves every feed at `GET /api/lab/feeds` (desktop app: the
`lab_feeds` command), worst status first, then newest.

## The header

Five fields at the top level of the JSON. Everything else in the file is kept
for the job's own use and ignored by the feed.

| field        | type            | meaning                                                         |
|--------------|-----------------|-----------------------------------------------------------------|
| `title`      | string          | What the card is called, in plain words: "New listings".        |
| `updated_ms` | integer         | When the job ran, Unix milliseconds. File time if missing.      |
| `status`     | `ok` `watch` `bad` | Green, amber or red. Anything else shows as unknown.         |
| `headline`   | string          | One sentence a beginner can read: what happened, and so what.  |
| `items`      | array           | The rows under the headline, at most 50.                        |

camelCase spellings (`updatedMs`, `atMs`) are read too.

Each item is either a plain string or an object:

| field        | type            | meaning                                                         |
|--------------|-----------------|-----------------------------------------------------------------|
| `label`      | string, required| The row's name: a coin, a model, a book.                        |
| `value`      | string or number| Shown on the right, as written: "+2.1 %", "new".               |
| `status`     | `ok` `watch` `bad` | The row's own colour.                                        |
| `detail`     | string          | One line under the label: why it matters.                       |
| `link`       | string          | A web link, or `study:<name>` to open `results/<name>.md`.      |
| `importance` | number 0..100   | How much it matters today. Home shows the top three.            |
| `at_ms`      | integer         | When the row happened, if not when the job ran.                 |

A file without the header still shows, with a title from its folder name and
a headline from its `verdict` or `headline` field, marked as not following the
convention.

## Example

```json
{
  "title": "New listings",
  "updated_ms": 1792059000000,
  "status": "watch",
  "headline": "Alpaca added SUI/USD today. It is too new for any strategy to trade.",
  "items": [
    {"label": "SUI/USD", "value": "new", "status": "watch",
     "detail": "Listed on Alpaca today; needs 60 days of history first.",
     "link": "study:alpaca_universe", "importance": 85}
  ]
}
```

From Python:

```python
from lab import report

data = {...}  # whatever the job keeps for itself
data.update(report.feed_header("New listings", "watch", headline, items))
report.write("listings", markdown, data)
```

`feed_header` checks the status and that every item has a label.

## How Home picks its three insights

From every feed and from the forward report and learning loop, the app takes
candidates and scores them:

- an item's own `importance`, or 60 for a `bad` feed's headline and 35 for a
  `watch` one;
- a paper book or autopilot below its backtest's band: 75, otherwise worth
  watching: 40;
- a model promoted by the learning loop: 70, rejected: 35;
- half the score after 36 hours, nothing after a week.

The forward report and the learning loop write the header too, so they show
up in any reader of the feeds; where the app has their full reports it uses
the plain sentences above instead of their feed items.

The three highest, at most one per feed, are shown. With nothing above 20, the
card says all is quiet. The code is `pickInsights` in `src/labFeeds.ts`.

## Where it shows

- **Home**, "Today in the lab": the three insights. Hidden without an engine.
- **Lab** (advanced view): the paper books, forward tests and verdicts, and
  the **pump.fun lab** (below).
- **Research** (advanced view): the same insights, every strategy book with
  its backtest, forward test, gate 7 progress and the autopilots running it,
  the model scores and registry decisions, what the learning loop changed,
  every other feed as a card with its items, and every study.

## Study write-ups

`results/<name>.md` (the markdown `report.write` copies when
`PYTHIA_RESULTS` is set) is the full write-up of a study. The app ships the
copies in the repository and the engine serves newer ones from
`PYTHIA_LAB_RESULTS`, else `<PYTHIA_DATA>/results`, at `GET /api/lab/studies`.
The Research page takes each study's one-line verdict from its row in the
"Results so far" table of `research/lab/README.md` (a row that says
`See results/<name>.md` is linked to that write-up), the families of the
strategy sweep from the sweep table, and any other write-up from its first
`**Verdict: ...**` paragraph, so start the results section with one. The
write-up's first `# ` heading is its title.

## Staying current

The Lab and Research pages read their endpoints again every 30 seconds
while the page is the one shown and the browser tab is in front, and say
"updated hh:mm" next to Refresh. A hidden page reads nothing.

## The pump.fun lab

`GET /api/lab/pumpfun` (read only, the same root as `/api/lab/feeds`;
`labview_pumpfun.rs`) serves the Lab page's pump.fun section:

- from `reports/pumpfun_rt/latest.json`: `status`, `headline`, `caveat`,
  `pick`, `readiness` (per pipeline strategy: days, trades, mean, the
  checks and `ready`) and `shadow` (the shadow books), as written;
- `reports/pumpfun_rt/execution.json` as written;
- `books`: the paper books of the pipeline strategies (the names in
  `readiness`, else every `P_` rule) from `paper/pumpfun_rt/ledger.csv`,
  closed entries of the last 7 days: entries, wins, mean per entry, P&L in
  SOL, one row per UTC day (newest first), a running P&L curve for the chart
  and the ten newest entries. Only the last 16 MB of the ledger are read.

The section also lists the newest `results/pumpfun_*.md` write-ups with
their titles and verdict lines, the same way the Research page reads them.
The desktop app has no reader for the endpoint yet; it shows the studies only.

