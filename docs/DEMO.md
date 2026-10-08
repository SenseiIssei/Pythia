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
For equities, Alpaca paper.

Nothing in this branch has sent a request to any demo host: every response shape
is from the docs, the same state as the live connectors (see `NEXT-STEPS.md` §1).
The first demo connection test is the check.

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
  a restart), always crosses (the execution bandit neither chooses for it nor
  learns from it), and is costed with the demo exchange's costs.
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

The execution policy keeps paper and demo fills in their own bounded lists
(`"{route}:{venue}"`), so the frequent paper fills never push live ones out. The
Strategy Passport's slippage check uses what venues reported (live and demo),
never Pythia's own paper arithmetic. Per strategy, order rows carry the strategy
id, so a report can group paper vs demo vs backtest by strategy from the order
log; the Analytics table groups by venue and route.
