# Pokemon cards (W9), 2026-10-15

Data, forecasts, a paper collection in play money, and alerts. Nothing in
this work can buy or sell a card anywhere: the cards are physical and the
owner trades them by hand.

**Verdict: the pipeline runs on real prices, but with one day of our own history nothing can be forecast honestly yet; the API has two big holes (no Cardmarket since mid 2026, no prices for 2026 sets), so the EU side waits and new sets come from TCGplayer through tcgcsv.**

## Status in one paragraph

The collector ran for real on 2026-10-15 from the PC: 20,670 cards in 176
sets, 10,694 of them at $2 or more, 857 sealed products and 4,684 singles of
the newest TCGplayer groups, the ECB rate (1.1195). It took two attempts and
about 55 minutes: /sets answered 500 and 502 for minutes, single card pages
needed a minute of retries, one page failed six tries in a row. The job now
retries a page 8 times and the whole run 3 times from its day cache. Every
number below is one cross-section. Returns, the release curve from our own
snapshots, reprint effects and any forecast test need history: the first
honest 30-day forecast test is about 225 days away, the 90-day one about 345.
Until then every forecast shown is a fixed rule, labelled as such on the
Cards page, in the report, in the feed and in every alert.

## What the first real snapshot showed

### Two holes in the Pokemon TCG API

- **Cardmarket is stale.** Not one of the 10,472 priced cards with a
  Cardmarket block had it refreshed in the last two weeks; the newest is
  2026-07-01, the median card's is 256 days old (10 % to 90 %: 106 to 331
  days). TCGplayer is current (10,660 of 10,694 updated within a week).
  So the planned "use Cardmarket's avg1 / avg7 / avg30 now" gives nothing
  current: those averages describe the spring. Every Cardmarket number
  (trend, averages, the US/EU spread, the trend regression, the
  Cardmarket-based move alert) now uses fresh rows only, and there are none.
  **There is no honest US/EU spread today.** It comes back by itself if the
  API refreshes Cardmarket again; the report and the feed say how fresh it is
  every day.
- **No prices for 2026 sets.** All 852 cards of the sets released in 2026
  (Perfect Order, Chaos Rising, Pitch Black, both 30th Celebration sets) have
  neither TCGplayer nor Cardmarket prices; the newest priced set is Mega
  Evolution (2025-09-26). The "behaviour around set release" question cannot
  be answered from this API. TCGplayer's own daily dump (tcgcsv.com, already
  read for sealed product) has them, so the collector now keeps their singles
  too and always takes the main sets of the last two years and the next
  releases.

### New sets on TCGplayer (tcgcsv), today

Chase average = mean of a set's 10 dearest singles. A cross-section of
different sets, not one set followed after release; our snapshots turn it
into a release curve after 30 days.

| Set | Released | Out | Chase average | Booster box |
|---|---|---|---|---|
| ME: 30th Celebration | 2026-09-16 | 29 days | $1,389 (three RGB Mews at $3,700 to $6,000) | n/a |
| ME05: Pitch Black | 2026-07-17 | 3 months | $47 | $184 |
| ME04: Chaos Rising | 2026-05-22 | 5 months | $39 | $185 |
| ME03: Perfect Order | 2026-03-27 | 7 months | $38 | $175 |
| ME02: Phantasmal Flames | 2025-11-14 | 11 months | $94 | $398 |
| ME01: Mega Evolution | 2025-09-26 | 13 months | $112 | $294 |
| SV10: Destined Rivals | 2025-05-30 | 17 months | $104 | $404 |
| SV09: Journey Together | 2025-03-28 | 19 months | $29 | $193 |
| SV08: Surging Sparks | 2024-11-08 | 23 months | $81 | $295 |

The three main sets of 2026 sit at $175 to $185 a box and $38 to $47 for
their chase cards; most sets a year or more old are dearer on both. That
fits "boxes rise once a set is out of print", but popularity differs by set
(Journey Together is old and cheap), so it is a description, not an effect.
The median single of a main set is about $0.30: almost all value sits in a
few cards.

### What a card's price is made of (OLS, 10,694 cards, one day)

Log price on rarity group, character, alt art, secret number, set age and
card type, HC1 t-statistics, R2 0.33. Premium against a common,
non-character Pokemon card of the same set age.

| Feature | Premium | t |
|---|---|---|
| holo | +147 % | 22 |
| ultra (ex, V, GX ...) | +323 % | 33 |
| chase (illustration, secret, gold, shiny ...) | +369 % | 23 |
| promo | +127 % | 18 |
| Charizard | +378 % | 13 |
| Mew or Mewtwo | +266 % | 11 |
| Rayquaza, Lugia, Gengar, Greninja, Lucario, Gardevoir | +255 % | 15 |
| Pikachu | +229 % | 12 |
| Eeveelutions | +205 % | 17 |
| alt art | +37 % | 3.5 |
| secret number | +92 % | 6.1 |
| trainer or energy | -42 % | -16 |
| set age, per unit of log(1 + years) | +394 % | 55 |

Charizard is the dearest character, as expected, then Mew, the legendary
group and Pikachu. Caveat: only cards at $2 or more are collected, so old
commons are in the sample only when they are valuable; the floor biases the
rarity and age premiums (old cheap cards are missing), not the character
ones within a rarity.

### Fair value

LightGBM of log price on what a card is (rarity group, character, alt art,
secret number, printing, subtypes, HP, number position, set size, set age,
series) plus how dear the rest of its set is (leave-one-out mean log price
of the other cards of the set and of its rarity group), five folds grouped
by set. Out of fold R2 0.64; the typical card is off by a factor of 1.75
either way (median absolute log error 0.56), 61 % are within 2x and 5.5 %
are more than 5x off. The first version (no set level, promos in "holo")
valued a $10 Black Star promo at $278; promos are now their own group.
This is a rough comparison with similar cards, not a price target.

### Other first-day facts

- Reprints: 3,066 reprint events in the catalogue (same name, HP, attacks
  and abilities in a later set); 102 priced cards had their text reprinted
  in the last 90 days. The effect needs 30 days of our snapshots.
- TCGplayer's cheapest listing is under 80 % of the market price for 67 %
  of cards (median 69 %): "low" includes played copies, so it is a weak
  signal on its own. It is a feature of the forecast model, which will tell.
- Printings priced: holofoil 4,906, reverse holo 4,577, first edition 757.
  The dearest card: Mewtwo Star (Holon Phantoms) at $9,200.

## The forecast and the paper collection

- **Prior rule** (until a horizon validates): 90 d = 0.10 x g, 30 d = 0.04 x
  g, where g is log(fair / price) squashed towards a factor of 3 and set to
  0 beyond a factor of 5 (model error), plus 0.3 x the fresh Cardmarket
  trend (none today). The best forecast today is about +10 % in 90 days. The
  first version used 0.25 x the raw gap and put every old card at its +50 %
  cap; that rule had no evidence behind it and was cut back.
- **Model**: walk-forward by month, purged by the horizon, validated only
  with 4 test months, mean rank IC above 0.03 with t above 2 and a lower
  error than forecasting zero. On synthetic markets the machinery finds a
  planted signal (rank IC 0.37, t 9.3) and rejects noise (-0.03). On real
  cards: not yet testable.
- **Paper collection**: $1,000 of play money, the 10 best 90-day forecasts
  between $20 and $250, at most four copies each, monthly; buying pays
  market + 3 % + $1.50 a copy, selling gets market - 15 % - $1.00. It started
  2026-10-15 at **-21.1 %** after costs on its first day (worth $935 at
  market, $788 if sold): the honest cost of trading cards by mail. The first
  version bought 13 copies of a $5.51 Geodude and stood at -33 %. A card has
  to rise about a quarter (at $100) to a third (at $20) to break even.
- **Alerts** (Telegram through `lab.ops.notify`): moves of 20 % in a day or
  35 % in a week on cards of $20 or more (from the second snapshot on), and
  cards at $10 to $500 whose fair value is 2x to 3x the price, from sets at
  least 60 days old, with a positive forecast. The first real run would have
  sent 5 such cards (Ho-oh promo, Terrakion-EX, Nidoking 151 ...), each
  labelled "fair-value model only; the return forecast is not validated".
  Seven days of cooldown per card.

## How long until real answers

| Question | Possible from |
|---|---|
| Rarity and character premiums, fair value, new-set cross-section | now |
| Strong-move alerts from our own prices | the second snapshot |
| Release curve of new sets (tcgcsv), release and reprint panels | 30 days |
| US/EU spread, Cardmarket trends | when the API refreshes Cardmarket again |
| A first honest test of the 30-day forecast | about 225 days |
| The same for 90 days | about 345 days |

## Sources

| Source | Reachable | Used for |
|---|---|---|
| api.pokemontcg.io v2 (cards, sets) | yes, slow and flaky (5xx for minutes) | every card up to 2025, TCGplayer prices, the stale Cardmarket block |
| tcgcsv.com (TCGplayer daily dump) | yes | sealed product, singles of new sets, pre-order prices |
| images.pokemontcg.io, tcgplayer-cdn.tcgplayer.com | yes | card pictures on the Cards page |
| ECB reference rates | yes, once failed at the start of a run | EUR/USD; asked again after the card loop |

## What is built

| Part | Module |
|---|---|
| Collector | `lab.collect.pokemon` (`--sealed` adds tcgcsv sealed product and new-set singles) |
| Features, studies | `lab.pokemon.data`, `lab.pokemon.study` (release, new sets, reprints, premiums, spread) |
| Fair value, forecast, prior | `lab.pokemon.model` |
| Paper collection | `lab.pokemon.collection` |
| Alerts | `lab.pokemon.alerts` |
| Daily job | `lab.pokemon.daily`: `pokemon/ui/latest.json` (Cards page), `reports/pokemon/latest.{md,json}` with the lab feed header, a monthly report on the first run of a month |
| App | `src/pages/Cards.tsx` in the calm design (key numbers, sortable list with pictures, a sheet per card with its price line and forecasts, new sets, the paper collection), `/api/pokemon`, `pokemon_status` |

Operator steps and the cron line: `research/ops/README.md`, "Pokemon cards".
Tests: `python -m pytest tests/test_pokemon.py` (34), from `research/lab`.
