# Demo trading: real venue API, virtual money

"Can't you first trade with made-up money, but through real trades, and then
calculate and analyse?" Yes. Pythia now has three routes for an order, and every
fill says which one it took:

| route | where the order goes | money | what it proves |
|---|---|---|---|
| **paper** | nowhere: Pythia fills it itself, walking the venue's live order book | none | the strategy, at an honest price for its size |
| **demo** | the venue's own demo or paper environment, through the real connector code | virtual | keys, signing, sizing rules, rejects, latency, partial fills, status polling |
| **live** | the real venue | real | everything, with consequences |

Demo needs **demo keys** for the venue, never the live arm, and never a green
Strategy Passport (nothing real is at stake). It still passes the risk manager
(kill switch, daily loss, size caps) like every other order. Demo fills are
booked in the same paper ledger as paper fills, at the price the venue reported,
and are **never written to the tax record** (`fills.jsonl`).

## Which venues have a demo, and how honest is it

Researched against each venue's current official docs on 2026-10-07. The same
links are in the connector code next to the base URLs.

| venue | demo base URL | how to get demo keys | real prices? | known differences |
|---|---|---|---|---|
| **Bybit** ([docs](https://bybit-exchange.github.io/docs/v5/demo)) | `https://api-demo.bybit.com` | Log in at bybit.com, switch to **Demo Trading** (a separate account with its own user id), avatar > API, create a key there. | **Yes.** Public market data is identical to mainnet and "basic trading rules are the same as real trading". | Demo orders kept 7 days. Default rate limits, not upgradable. WS trade not supported (Pythia uses REST). Top up virtual funds from the Demo Trading page (capped per request). A mainnet key does not work on the demo host and vice versa. |
| **Binance** ([Spot Demo Mode](https://developers.binance.com/en/docs/products/spot/demo-mode/general-info)) | `https://demo-api.binance.com` | Log in at binance.com, open **Binance Demo Trading**, create a key on its API Key Management page. | **Close to real.** "Demo Mode's prices and order books are similar to the live exchange"; filters, limits and unfilled-order counts are exactly the live ones. Binance warns that realistic is not real. | Balance resettable any time in the UI. No orders during announced maintenance. Not the **Spot Testnet** (`testnet.binance.vision`, GitHub login): the testnet has its own prices and order book, independent of the live exchange, resets monthly, and is not what Pythia's demo route uses. |
| **OKX** ([docs](https://www.okx.com/docs-v5/en/#overview-demo-trading-services)) | same REST host as live, plus header `x-simulated-trading: 1` | Log in at okx.com, Trade > Demo Trading > Personal Center > **Demo Trading API**, create a demo key with its own passphrase. | **Not documented.** OKX runs its own demo matching engine; prices follow the market, but OKX does not say whether its demo book has real depth. Treat demo fills there as proof of the API path, not of the price. | A key from the wrong world answers `50101 APIKey does not match current environment` (mapped to an auth error). Demo keys do not expire. `instIdCode` may differ between production and demo (Pythia uses `instId`). OKX's overview now lists `https://openapi.okx.com` for both worlds; the connector keeps `https://www.okx.com`. |
| **Alpaca** ([docs](https://docs.alpaca.markets/docs/paper-trading)) | `https://paper-api.alpaca.markets` | Alpaca dashboard, switch to the **paper** account, generate its keys (separate from live keys). Already supported. | **Yes, quotes.** Orders match against the real-time NBBO. | Order size is not checked against displayed liquidity (a big order fills beyond the book), about 10 % of eligible orders get random partial fills, no market impact, no latency slippage, no price improvement, no regulatory fees, no dividends. |
| **Kraken** ([docs](https://docs.kraken.com/home/guides/quickstart)) | none | Spot UAT exists only on request through a Kraken account manager. The self-service sandbox (`demo-futures.kraken.com`) is futures only. | n/a | **No demo route.** A demo connector for Kraken fails closed before any request is built. |
| **Coinbase** ([docs](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox)) | (`api-sandbox.coinbase.com`, not used) | none needed | **No.** "All responses are static and pre-defined." | **No demo route**: a sandbox that always answers the same fill has nothing to analyse. Fails closed like Kraken. |

**Best venue to start on: Bybit Demo Trading.** Mainnet prices, mainnet rules,
self-service keys, and spot trading on the same v5 endpoints the live connector
already uses. Binance Demo Mode is the second choice (prices "similar to live").
For equities, Alpaca paper. With only Alpaca paper keys, crypto demo can run on
the Alpaca paper account too (next section).

## Crypto demo on the Alpaca paper account

`PYTHIA_DEMO_EXCHANGE=alpaca` (backend `.env`) sends the crypto venue's demo
orders (`crypto:BTC/USD` and the rest, what the lab books trade) to Alpaca's
crypto book on the **paper** account. No extra keys: it uses the
`APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` paper pair, only against
`paper-api.alpaca.markets`. The live pair (`APCA_LIVE_*`) is never read for it.
A demo exchange with keys of its own (`PYTHIA_DEMO_EXCHANGE=bybit` plus its
keys) keeps working exactly as before; the two are one setting, so pick one.

- **Symbols.** Pythia's `BTC/USD` is Alpaca's `BTC/USD`. Alpaca crypto here is
  USD-quoted only; orders go out in coins, fractional, GTC, as maker limits
  at the touch by default (next section), as market orders when that is off
  or an exit must not wait.
- **What Alpaca lists.** Alpaca does not list every coin of the 20-coin
  universe. At startup (before the first tick, at most 20 s) and then once a
  day the server reads `GET /v2/assets?asset_class=crypto&status=active` from
  the paper API and keeps the tradable USD pairs (a failed read is retried
  after 10 minutes). A demo order on a coin Alpaca does not list is refused
  with "not listed on Alpaca"; the connector's own asset check refuses it too,
  even before the list is read. The Live page's demo card names the skipped
  coins (`live.demoNotListed`).
- **Autopilots.** A demo autopilot on crypto trades on Alpaca (its venue is
  `alpaca`, asset class `crypto`; the Autopilot page sends both). Its sleeves
  only get the coins Alpaca lists. A lab book whose target holds an unlisted
  coin trades the rest and leaves that coin's share in cash: the weights are
  not scaled up. The rebalance line in the journal names the skipped coins
  once per rebalance. Venue `alpaca` without an asset class is still US shares.
- **Several autopilots on the one paper account.** Each autopilot is a
  sub-account with a book of its own (positions kept under
  `autopilot id|market`), so two of them can hold BTC at once, each with its
  own quantity, fills, fees, P&L, cash and equity curve. Each sends its own
  orders; every fill is booked to the autopilot whose order it was. An order
  on the other side of a coin from another autopilot waits until that one is
  done (Alpaca refuses opposite orders that could meet as a wash trade). Paper
  and demo autopilots may run the same strategy or lab book, each in its own
  book; a live one keeps its strategies to itself. Together the demo
  autopilots here may be given no more than the paper account's equity, which
  the server reads before a start or a raise; lowering one autopilot's amount
  frees the room for another. Stopping one closes only its own book.
- **Costs and fills.** Fills are what Alpaca reports; slippage against the
  engine's price is recorded like any demo fill. The modelled side uses the
  `alpaca` entry of `config/costs.json` (crypto pairs: 0.25 % taker, 0.15 %
  maker; spreads beyond BTC and ETH are unmeasured guesses). Alpaca posts the
  crypto fee later as a `CFEE` activity; the fee booking below covers these
  fills too, read from the paper account. Demo fills and their fees never
  enter the tax record.
- **Prices.** Alpaca paper fills against Alpaca's own real quotes, so a demo
  autopilot is allowed (unlike OKX). Pythia's crypto marks come from its feeds
  (Kraken first), so a small gap between the two books is normal and shows up
  as slippage.
- **One account, one position per coin.** `alpaca:BTC/USD` (Alpaca's own
  market, used by the Alpaca connection test) and `crypto:BTC/USD` on this
  route land in the same BTC position of the paper account. Pythia keeps them
  apart in its own book and every exit sells only its own quantity. The
  reconciliation below compares their sum with the paper account, and the
  live arm's reconciliation on the paper endpoint leaves the demo book's
  coins out of the position it compares.
- **Reconciliation.** At startup (after 15 s) and every 10 minutes the server
  reads the paper account's crypto positions and open orders and compares
  them with the demo book per Alpaca pair (`engine::demo_reconcile`). Equal up
  to rounding (a billionth of the position, or under a cent) is quiet. A pair
  with an order in flight waits for that order's report. A gap the unposted
  fees of the watched buys explain is booked as those fees. The comparison is
  Alpaca's quantity against the sum over every autopilot's book. When demo
  positions of one market hold the pair and nothing is open, Alpaca wins: one
  book takes Alpaca's number, several share it in proportion to what each
  held, and each autopilot books its own difference at the mark. A position at
  Alpaca the book does not have is adopted only when exactly one market on
  the route has Pythia demo orders in that pair; anything else (several
  markets share the pair, an open order Pythia does not follow, a coin Pythia
  never traded there) is reported, never guessed. Each finding is journaled
  once; the Live page shows the result (`live.demoReconcile`).
- **Size rules.** Each crypto asset's `min_order_size`, `min_trade_increment`
  and `price_increment` (from `GET /v2/assets`) are applied before sending:
  quantities are rounded down to the step with up to 9 decimals, limit prices
  sit on the price step, and an order below the minimum is skipped with one
  journal note per 6 hours instead of being sent to be refused.
- **Refusals.** Insufficient balance (15 min), wash trade (5 min), any other
  422 (30 min) and below the minimum (30 min) hold that market back; a 403 on
  the keys or the account holds the whole route for 15 minutes, and the
  orders already queued are closed without a request. Each kind is journaled
  once per window (an hour; 6 hours for the minimum), with a count of the
  ones kept quiet. Alpaca answers balance and wash trade refusals with 403
  too; those are read as refusals, not as a key problem.
- **A fee that never comes.** It is not known whether the paper account
  posts `CFEE` at all. A fill still without a posted fee after 7 days gets
  one from the published tier 1 rate (25 bps taker, 15 bps maker) on its
  notional, in dollars only, so the coins keep matching Alpaca. It is marked
  ESTIMATED in the journal and listed on the Live page, and never written to
  the tax record.
- **Desktop app.** Backend only for now: the desktop app keeps the demo
  exchange slots.

### Maker orders on the Alpaca crypto demo route

Alpaca charges crypto 0.25 % taker and 0.15 % maker per side
([fee table](https://docs.alpaca.markets/docs/crypto-trading)). A market
order pays the taker fee and the half spread; a limit that rests and is
filled by someone else pays the maker fee and earns the spread. So crypto
demo orders on the Alpaca paper route are worked as maker orders by default:

1. **Rest.** A GTC limit at the best bid (buys) or best ask (sells) of the
   engine's live order book for the coin (the crypto feed's book, Kraken
   first), rounded to six significant digits away from crossing.
2. **Re-price.** Not filled after `restSec` (20 s): cancelled, and placed
   again at the current touch for what is still open. Up to `maxTries` (3)
   resting limits in all.
3. **Fall back.** Then the rest goes out as a marketable limit, IOC, up to
   `fallbackBandBps` (50 bps) past the far side of the book (never better
   than the last price), and whatever the IOC leaves goes out as a market
   order. A limit Alpaca refuses goes straight to the market order. A
   rebalance is therefore done after about `restSec x maxTries` plus two
   order timeouts, whatever the book does.

Each limit is a separate Alpaca order; the first keeps the order's client id,
later ones add `-m1`, `-m2`. Partial fills carry over: the next limit is for
what is still open, and every part is booked into the one order row.

**Maker or taker.** Alpaca crypto has no post-only flag (limit orders take
`gtc` or `ioc`), so a limit that is marketable when it arrives simply fills
as a taker. Pythia counts a fill as **maker** when a resting limit filled at
its own price (within 0.5 bps, the rounding), and as **taker** when it filled
better than the limit (it crossed on arrival) or came from the fallback. The
touch is the feed's book, not Alpaca's, so when the two books disagree some
"resting" limits cross; the maker share on the order row says how often.

**What is recorded.** Per fill a journal line (`filled as maker, resting at
our limit ...` or `as taker ...`); per order, on the order row:
`makerQty`, `takerQty`, `realisedCostBps` (slippage against arrival plus the
fee rate of the maker and taker mix, from `config/costs.json`) and
`modelledCostBps` (what the cost model charges the same order as a market
order: modelled slippage plus the taker fee), and a closing journal line
(`done: 80% maker ...; cost 9.3 bps (fee 17.0) against 26.5 modelled for a
market order`). The Analytics trade log shows both. The fee actually charged
is still the `CFEE` activity Alpaca posts later (above).

**No book yet.** Right after a restart the order book feed needs a few
seconds to load. A non-urgent order (a lab rebalance, a strategy signal, a
hand-placed demo order, a risk trim) then waits for a fresh book instead of
crossing, with one journal line, for at most 10 minutes. A lab rebalance
waits whole, so its sells and buys stay together. If no book comes in that
time, the order starts at the fallback (a marketable limit IOC a
`fallbackBandBps` band past the last price, then a market order for the
rest) and counts as a fallback without a book. A resting limit whose book
went stale is placed again at the same price rather than crossing early.

**Statistics.** Each finished maker order is kept for 30 days (saved with
the engine state). Per route, over the last 7 and 30 days: the maker fill
rate by quantity and by order (orders filled entirely as maker), the
average resting time, the notional-weighted realised cost against the
modelled market-order cost, and the fallback count (and how many of those
had no book). They are in `/api/state` as `live.makerStats`, at
`GET /api/execution/stats`, and on the Live page's demo card.

**What never rests.** Stop-loss and take-profit exits, an autopilot's
flatten at stop, and a manual flatten go out as market orders. An exit like
that in a coin with a resting maker order makes the maker order stand down
first. Every other route (Bybit, OKX and Binance demo, paper, live) is
unchanged, as is adaptive execution.

**Nothing left behind.**

- Every limit is saved with its order. After a restart it is polled again;
  one that was queued but not acknowledged is looked up by its client id
  (found: followed; not at Alpaca: the next limit is sent).
- At startup, before anything new is sent, the server lists the paper
  account's open crypto orders (`GET /v2/orders?status=open`). An order
  Pythia sent (client id `pythia-...`) that an order here is waiting for is
  adopted; one nothing here knows of is left from an earlier run and is
  cancelled, with a journal line naming its client id. Orders not sent by
  Pythia are never touched. A failed listing is tried again every minute.
- Stopping an autopilot cancels its resting maker orders at once; nothing
  new is placed for them, and what already filled stays booked.

**Setting.** Per route, keyed `demo:alpaca:crypto`, saved with the engine
state and shown as `live.makerRoutes`. Change it with
`POST /api/live/maker` and a body like
`{"route":"demo:alpaca:crypto","settings":{"enabled":true,"restSec":20,"maxTries":3,"fallbackBandBps":50}}`,
the button on the Live page's demo card, or `PYTHIA_ALPACA_MAKER=off`
(`on`) in the backend `.env`, applied at every start. Only this route can be
switched on for now: the fallback needs IOC limits and the startup check
needs an open-order listing, which only the Alpaca connector has.

Not verified against the paper account from this branch: that Alpaca paper
fills a resting crypto limit at its limit price, that it accepts six
significant digits for every pair's limit price, and the open-order listing.
The logic is covered by tests against a scripted venue
(`engine/maker_tests.rs`).

Verified against the real paper account: a demo connection test order
`alpaca:BTC/USD` fills through the Alpaca connector. The crypto-venue route
reuses that connector; the asset list call is from Alpaca's reference
(`get-v2-assets-1`) and was not called from this branch.

Nothing in this branch has sent a request to any demo host: every response shape
is from the docs, the same state as the live connectors (see `NEXT-STEPS.md` §1).
The first demo connection test is the check.

## US shares and ETFs on the Alpaca paper account

**Which symbols.** The engine quotes and trades a configurable list of US
equities on Alpaca (`alpaca:<SYMBOL>` markets, IEX feed unless set otherwise).
`PYTHIA_EQUITIES` (backend `.env`, comma or space separated, for example
`PYTHIA_EQUITIES=SPY,QQQ,TLT,IEF,GLD`) wins; else `PYTHIA_EQUITIES_FILE`
names a file with one list (new lines and `#` comments allowed); else the
default is the five stocks (AAPL NVDA MSFT AMZN TSLA) plus the 15 ETFs of the
lab's `etf_trend` study (SPY QQQ IWM TLT IEF GLD SLV XLE XLF XLK XLV EFA EEM
VNQ DBC). A setting with no valid ticker falls back to the default. The five
stocks stay seeded either way (the default strategies name them); left out of
the list they get no quotes and stay on the simulator. A symbol that is not
one of the five starts at a placeholder price of 100 that never moves and is
real from its first Alpaca quote; nothing trades it before then.

**Lab books of US shares.** A lab signal with `"asset_class": "us_equity"`
names ETFs and shares (`"SPY": 0.3`), traded as `alpaca:SPY`; a key that is
already a market id (`"alpaca:SPY"`) is taken as it is. Signals without the
field are coins, as before. Such a book is created on venue Alpaca, so an
autopilot on venue `alpaca` without an asset class (US shares) can claim it;
in demo mode its orders go to the Alpaca paper account.

- **Regular session only.** The rebalance waits until the broker status says
  the regular session is open, whatever the extended-hours setting: the lab
  filled at regular-session closes. Before that it is queued and the journal
  says so once per signal ("Lab rebalance queued: US regular session closed
  (next open ...)"). Sells wait too, so a rebalance is never half done. The
  signal must still be valid when the session opens, so a weekly book's
  validity window has to cover the weekend.
- **Sizing.** Orders are sized in dollars. Buys of fractionable symbols go out
  as Alpaca `notional` market orders, sells as fractional share quantities
  (reduce only); the connector handles both, as for any Alpaca order.
- **Costs.** No commission; spread and slippage from the `alpaca` entry of
  `config/costs.json`.

Not yet verified against the paper account: no ETF order has been sent from
this branch. The tests drive the engine with hand-set quotes and broker status.

## What the owner does to start demo trading on Bybit

1. bybit.com > log in > **Demo Trading** (top right). In the demo account: avatar >
   **API** > create a key, permissions *Read-Write* for Spot trade. Note key and secret.
   If the demo wallet is empty, request demo funds on the Demo Trading page.
2. Pythia desktop: **Settings > Exchanges > Bybit > Demo keys (virtual money)**,
   paste the demo key and secret, **Save demo keys**. They go to their own
   keychain slot (`exchange-demo:bybit`); the live Bybit slot is not touched, and
   Pythia refuses to save the same key into both.
   Backend instead: `PYTHIA_DEMO_EXCHANGE=bybit`, `PYTHIA_DEMO_EXCHANGE_KEY`,
   `PYTHIA_DEMO_EXCHANGE_SECRET` in `.env`, restart.
3. **Live page > Demo trading card > Crypto exchange**: *Check demo account*
   (read-only, shows the demo balances), then *Demo connection test* (one BTC buy
   at the venue minimum, virtual money). The journal should show
   `DEMO submit` then `DEMO FILL`, the position carries a purple **DEMO** badge.
   Cross-check the fill in Bybit's demo order history.
4. **Strategies**: press **Demo** on a crypto strategy. Its entries now go to Bybit
   demo; its exits go back there too. No arming, no passport.
5. After a few days, **Analytics > Execution**: the slippage table has a row per
   venue and route. Compare `bybit · demo` (what a matching engine actually did)
   with the `paper` row (Pythia's book walk) and the model.

## How it works in the code

- `connectors::Environment { Live, Demo }`. A `CexConnector` is built for one
  environment with that environment's keys (`CexConnector::with_env`); its
  `base()` picks the demo host, OKX adds `x-simulated-trading: 1` (and now sends
  `0` explicitly on live). `Exchange::demo()` holds the table above; `None` fails
  closed.
- Keys: `vault::exchange_demo_slot(id)` (`exchange-demo:<id>`) and the field
  `demoExchange` in the `crypto` slot. `execution::Credentials::exchange_demo`.
  `Credentials::connector_env(venue, env, paper, extended)` is the one place a
  connector is built for an order or a poll: live uses only live keys, demo only
  demo keys, and a demo key equal to the live key of the same exchange is
  refused. Alpaca demo is always the paper pair against the paper host.
- Engine: `RouteIntent::Demo`, `StrategyState::Demo`, `Engine::set_demo_venues`
  (hosts call it when credentials change). A demo order runs the same in-flight
  machinery as a live one (`LiveOrderOut.demo`, `LivePoll.demo`, restored after
  a restart), crosses unless its route works maker orders (the Alpaca crypto
  demo route by default, `engine/maker.rs`; the execution bandit neither
  chooses for a demo order nor learns from it), and is costed with the demo
  exchange's costs.
- Booking: a demo fill settles with `live = false, demo = true`. The position is
  flagged demo (persisted), its exits route `Demo`, reconciliation never touches
  it, and its closed trades count as `demoTrades` (and as forward trades only on
  venues that document real prices).
- One position per market: a demo order into a market holding a paper or real
  position is refused, and so is a paper or live order into a demo position.
  Pause the other strategy or use another market.
- If the demo keys disappear while a demo position is open, its exit is
  simulated and the journal says so (`SIMULATED`), so nothing is stuck forever.
- Alpaca's **paper endpoint under the live arm** (`LiveConfig.paper`) is virtual
  money too: its fills are now labelled `demo` and **no longer written to the
  tax record**. Positions from it keep the `live` flag as before (they are
  reconciled against the paper account).
- A demo whose prices are not documented as real (OKX): a strategy set to Demo
  there keeps working, and the Strategies and Live pages say its numbers are
  an **API test, not a price test**. A **demo autopilot** there is refused at
  start: its fills would be measured in another price world than the one its
  stop rules watch. A crypto demo autopilot's venue is the demo exchange.
- Fees: on a spot buy Bybit, OKX and Binance keep their fee in the coin
  bought. Every fill books the coins actually received and the fee in dollars
  at the fill price, so the position matches the demo (or live) account and
  the exit sells what is there.
- Alpaca crypto fees work differently: Alpaca charges them in what the trade
  credits (a BTC/USD buy pays in BTC, a sell in dollars), its order object
  has no fee field, and the fee is posted at the end of the day as a `CFEE`
  or `FEE` account activity
  ([docs](https://docs.alpaca.markets/docs/crypto-trading)). Pythia books
  the fill as filled, waits for the fee, and reads the activities every half
  hour while it waits (paper and live accounts alike). A posted coin fee
  leaves the position, the fee goes into the strategy's and the autopilot's
  fees in dollars at the fill price, and the journal says so. If the account
  shows the coins gone earlier (reconciliation, or an exit that sold what
  the account held), that gap is booked as the fee at once and the posting
  only confirms it. Whether the paper account charges these fees is not in
  Alpaca's docs; if no fee is posted within a week the journal says so.
  Equities are unchanged: commission-free, regulatory fees not modelled.
- A demo order that was sent but not yet acknowledged when Pythia stopped is
  looked up at the demo venue by its client order id after the restart
  (Bybit `orderLinkId`, OKX `clOrdId`, Binance `origClientOrderId`, Alpaca
  `by_client_order_id`) and booked and followed, or closed when the venue has
  no such order. If the venue cannot be asked, the journal keeps the client
  order id to look for in the demo account.

### Routing an order as demo from other code (Autopilot)

```rust
use pythia_core::engine::{Engine, RouteIntent};
use pythia_core::connectors::Side;

// Through the risk manager and the router, attributed to a strategy id.
// Ok(qty) means routed (the fill arrives later from the venue), Err says why not.
engine.place_order("autopilot:momo", "crypto:BTC/USD", Side::Buy, 250.0, RouteIntent::Demo)?;

// Paper works the same way. Live is refused here on purpose: real money moves
// only for a strategy whose state is Live (green passport) or the connection test.
engine.place_order("autopilot:momo", "crypto:BTC/USD", Side::Buy, 250.0, RouteIntent::Paper)?;
```

The strategy id must exist in the engine (add it with `add_strategy` first).
Or set the whole strategy to `StrategyState::Demo` and let its signals route
themselves. `Engine::demo_venues()` / `EngineState.live.demoVenues` say which
venues can take a demo order right now; `place_order` returns an error naming
the missing keys otherwise.

## Paper fills that walk the book

`BookQuote` now keeps its top 20 levels per side (`Ladder`, fixed size so the
quote stays `Copy`). When a fresh book (under a minute) from the executing
exchange exists, a paper market order on a crypto market is filled level by
level from the best price (`BookQuote::walk`) at the VWAP of what it consumed,
plus the venue's taker fee from `config/costs.json`. If the order outgrows the 20
levels, the remainder is priced at the book mid plus the modelled half-spread
and impact for the whole order, never better than the last level, and the fill
is flagged (`bookExhausted`, a journal line, the *past book* count). Without a
fresh book it is the cost model around the signal price, as before. Prediction
markets and equities stay on the model (no live books for them).

## What every fill records, for the comparison

| field | on | meaning |
|---|---|---|
| `route` | order row, slippage record, slippage row | `paper`, `demo`, `live` |
| `costSource` | order row, slippage record (`source`) | the model (and a paper fill) used a fresh live book, or the calibrated default |
| `realisedSlippageBps` / `modelledSlippageBps` | order row, slippage record | fill against the signal price, next to the model's half-spread plus impact |
| `driftBps` | order row, slippage record (`medianDriftBps` on the row) | book mid against the signal price when the order was priced, positive = moved against the order |
| `bookExhausted` | order row, slippage record (`exhausted` count on the row) | a paper fill that ran past the 20 levels |
| `makerQty` / `takerQty` | order row (maker routes) | filled resting at our own limit, and by crossing |
| `realisedCostBps` / `modelledCostBps` | order row (maker routes) | slippage plus the fee of the maker and taker mix, next to the model's cost for a market order |

The execution policy keeps paper and demo fills in their own bounded lists
(`"{route}:{venue}"`), so the frequent paper fills never push live ones out. The
Strategy Passport's slippage check uses what venues reported (live and demo),
never Pythia's own paper arithmetic. Per strategy, order rows carry the strategy
id, so a report can group paper vs demo vs backtest by strategy from the order
log; the Analytics table groups by venue and route.
