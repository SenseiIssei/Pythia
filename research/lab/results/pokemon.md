# Pokemon cards (W9), 2026-10-15

Data, forecasts, a paper collection in play money, and alerts. Nothing in
this work can buy or sell a card anywhere: the cards are physical and the
owner trades them by hand.

## Status in one paragraph

The pipeline is built and tested end to end, but **there are no real price
results yet.** The Pokemon TCG API (and its image host) was not reachable from
the machine this was built on, so the first real snapshot will be the
server's first cron run. The only real data used here is the public card and
set catalogue (the API's own source data, mirrored on GitHub, no prices),
which was used to check the feature rules. Every forecast the system shows
until it has enough of its own history is a fixed rule, labelled as such on
the Cards page, in the report and in every alert. The model numbers below are
from **synthetic** markets and only show that the machinery finds a planted
signal and rejects noise; they say nothing about real cards.

## What is built

| Part | Module | What it does |
|---|---|---|
| Collector | `lab.collect.pokemon` | Daily snapshot of every card with a TCGplayer market price or Cardmarket trend of at least $2 (TCGplayer USD: low, mid, high, market of the dearest printing plus all printings as JSON; Cardmarket EUR: trend, average sell, low, avg1, avg7, avg30 and the reverse-holo fields), all sets with release dates, the full catalogue (cheap cards too, for reprints), the ECB EUR/USD rate, optionally sealed product from tcgcsv.com. Parquet under `pokemon/cards/date=.../`, `sets/`, `sealed/`, plus `meta/<date>.json`. Spacing 2.1 s keyless (0.3 s with `POKEMONTCG_API_KEY` from the environment), retries with exponential backoff and Retry-After on 429 and 5xx, no retry on 4xx, a same-day page cache so a rerun continues where it stopped. |
| Studies | `lab.pokemon.study` | Release curve, reprints, rarity and character premiums, TCGplayer against Cardmarket; each as a cross-section from the first day (on Cardmarket's rolling averages) and as a panel from our own snapshots once 30 days exist. |
| Fair value | `lab.pokemon.model` | LightGBM of log price on rarity group, character, alt art, secret number, set age, series, type and the Cardmarket trend features; five folds grouped by set, so no card is valued by a model that saw its set. |
| Forecast | `lab.pokemon.model` | 30 and 90 day log returns from the same features plus the card's own past returns and the fair-value gap. Monthly walk-forward, purged by the horizon, at least 45 labelled training days. Validated only with 4 or more test months, mean rank IC above 0.03 with t above 2, and a lower error than forecasting zero. |
| Prior rule | `lab.pokemon.model` | Until a horizon validates: 30 d = 0.10 x log(fair / price) + 0.30 x the Cardmarket 30-day trend, 90 d = 0.25 x log(fair / price) + 0.30 x trend, clipped to plus or minus 50 %. Not fitted, not validated; the paper collection is its forward test. |
| Paper collection | `lab.pokemon.collection` | $1,000 of play money. Monthly: the 10 best 90-day forecasts among cards at $5 to $250 with a forecast above +5 %; a card is sold after 90 days held once it falls out of the top 30, or when its price has been missing for 14 days. Buying pays market + 3 % + $1.50 a card, selling gets market - 15 % - $1.00 a card. |
| Alerts | `lab.pokemon.alerts` | Telegram (or the webhook): moves of 20 % in a day or 35 % in a week on cards of $20 or more (Cardmarket avg1 against avg7 before we have history), and cards at $10 to $500 at least 60 % below fair value from sets at least 60 days old with a positive forecast. Seven-day cooldown per card. |
| Daily job | `lab.pokemon.daily` | Runs all of the above after the collector, writes `pokemon/ui/latest.json` (the Cards page), `reports/pokemon/latest.{md,json}` (the Lab page) and on the first run of a month `reports/pokemon/monthly/<previous month>.md`. |
| App | `src/pages/Cards.tsx`, `/api/pokemon`, `pokemon_status` | A plain list: card image, name, price, change, 90-day forecast; sort by value, moves, forecast or cheapness; a detail view with the price line, both forecasts, fair value and links to TCGplayer and Cardmarket; the paper collection below. Visible in simple mode. |

## What the real catalogue says (no prices)

Checked on the API's public source data as of 2026-10-15: 20,635 cards in
176 sets released 1999-01-09 to 2026-09-16.

- Rarity: every one of the 44 rarity strings maps to a sensible group
  (common, rare, holo, ultra, chase; 295 cards without a rarity are other). A first substring rule put
  "Rare Holo VSTAR" in chase (because of "star") and the shiny vault cards
  in plain rare; word matching fixed both, with a test on the real strings.
- Characters found: 386 Eeveelution cards, 213 Pikachu, 147 Mew or Mewtwo,
  108 Charizard, 309 of the other chase favourites (Rayquaza, Lugia, Gengar,
  Greninja, Lucario, Gardevoir).
- Alt art (illustration rares and secret-numbered ultras) 1,731 cards;
  secret numbers 2,051. The API has no alt-art field, so this is an
  approximation from the rarity and the number.
- Reprints keyed on name alone would count 12,322 events (every new Pikachu
  card "reprints" every old one). Keyed on the card text (name, HP, attacks,
  abilities) there are 3,042 reprint events across 2,051 distinct cards; 160
  cards had their text reprinted in the 90 days before 2026-10-15, mostly by
  the 30th Celebration sets.

## Model machinery on synthetic markets (not real cards)

A made-up market of 8 sets x 30 cards over 240 days, collected through the
real collector against a fake API. Prices pull toward a hidden fair value at
6 % a day plus 3 % daily noise, or do not pull at all.

| Market | Horizon | Test months | Mean rank IC | t | Error vs zero | Validated |
|---|---|---|---|---|---|---|
| planted signal | 30 d | 4 | 0.374 | 9.3 | 0.090 vs 0.097 | yes |
| pure noise | 30 d | 4 | -0.033 | -1.0 | 0.141 vs 0.138 | no |
| either | 90 d | 0 | n/a | n/a | n/a | no (needs more history) |

The fair value recovers a planted 3x Charizard premium (measured above +80 %,
t above 3) on a single synthetic snapshot.

## How long until real answers

| Question | Possible from |
|---|---|
| Cross-sections (rarity and character premiums, set-age curve on Cardmarket averages, reprinted vs not, US vs EU spread) | the first snapshot |
| Strong-move alerts from our own prices | the second snapshot (before that, Cardmarket avg1 vs avg7) |
| Release and reprint panels from our snapshots | 30 days |
| A first honest test of the 30-day forecast | about 225 days (45 training days, the 30-day purge, four test months, and their labels) |
| The same for 90 days | about 345 days |

Card trading costs are large, which the paper collection shows from day one:
a $20 card bought at $22.10 all in fetches $16.00 sold at the same price, so
it has to rise about 36 % to break even ($100 card: about 24 %). A synthetic
first run marked the collection at -24 % on the day it bought, by costs
alone. Any forecast has to clear that, not zero.

## Sources

| Source | Reachable here | Used for |
|---|---|---|
| api.pokemontcg.io v2 (cards, sets) | no (blocked by this build machine's proxy) | everything priced; the server should reach it |
| images.pokemontcg.io, images.scrydex.com | no | card pictures on the Cards page (allowed in the desktop app's CSP) |
| GitHub mirror of the API's card data | yes | the catalogue checks above |
| tcgcsv.com (TCGplayer dumps, incl. sealed) | no | optional `--sealed`; untested against the live service |
| ECB reference rates | not tried here | EUR/USD for the spread and Cardmarket-only cards |

## Operator steps

See `research/ops/README.md`, section "Pokemon cards": one cron line at
07:05 UTC, an optional `POKEMONTCG_API_KEY` in `/etc/pythia/alerts.env`, a
read-only mount of `pokemon/ui` into the engine that serves the app, and an
optional `pokemon/reprints.csv` for announcements.

Tests: `python -m pytest tests/test_pokemon.py` (26), from `research/lab`.
