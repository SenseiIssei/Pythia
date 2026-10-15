# Lab feeds

Any lab job can show up in the app without touching the engine or the UI: it
writes one JSON file, and the Research page and the Home insights pick it up on
their next refresh.

## Where

```
<PYTHIA_DATA>/reports/<name>/latest.json
```

`<name>` is the job's folder name (`listings`, `trending`, `cs2`, `model_zoo`,
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
- a paper book or autopilot below its backtest's band: 75;
- a model promoted by the learning loop: 70, rejected: 35;
- half the score after 36 hours, nothing after a week.

The three highest, at most one per feed, are shown. With nothing above 20, the
card says all is quiet.

## Study write-ups

`results/<name>.md` (the markdown `report.write` copies when
`PYTHIA_RESULTS` is set) is the full write-up of a study. The app ships the
copies in the repository and the engine serves newer ones from
`PYTHIA_LAB_RESULTS`, else `<PYTHIA_DATA>/results`, at `GET /api/lab/studies`.
The Research page takes each study's one-line verdict from its first
`**Verdict: ...**` paragraph, so start the results section with one.
