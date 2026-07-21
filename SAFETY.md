# SAFETY — read this before going live

Pythia can place **real orders with real money**. That power is gated for good reason. This document
is the standing disclaimer and the operating rules. If you disagree with any of it, keep the app in
paper mode.

## 1. Not financial advice

Pythia is software, not an advisor. Nothing it displays is a recommendation to buy, sell, or bet.
Automated trading and prediction-market betting carry a **real and serious risk of losing all the
money you commit** — quickly, and while you are asleep. Only ever commit money you can afford to
lose entirely.

## 2. Legal / jurisdiction

- **Polymarket is geoblocked for US persons** and its use is restricted in several jurisdictions.
  Automated access must comply with Polymarket's Terms of Service and the laws where you live.
  Circumventing geoblocks (e.g. via VPN) can violate ToS and applicable regulations. **You are
  responsible for confirming that your use is legal where you are.** Pythia does not do this for you.
- **Automated equities trading** (Alpaca) is subject to Pattern Day Trader rules, market hours,
  and the broker's API terms. Pythia enforces some of these but you remain responsible.
- **Crypto** regulation varies by country; some venues restrict automated or API access.

## 3. How money actually gets committed (the gates)

1. Pythia starts in **paper mode**. No connector can move money without keys.
2. **You** enter API keys into the app; they go to the OS keychain, never into code or logs.
3. A strategy runs in paper until **you** promote it to live by typing its name to confirm.
4. The **risk manager** still sits above every live order (kill switch, daily-loss cap, size caps).

Claude (the assistant that built this) **never** enters your credentials, never funds an account,
and never executes a trade for you. The software does it, under your control, with your keys.

## 4. Your responsibilities

- Test every strategy in paper for long enough to trust it. A good paper result is necessary, not
  sufficient — slippage, fees, and thin liquidity make live worse than paper.
- Set the risk limits **before** arming anything live. Start tiny.
- Keep the kill switch reachable. Know how to flatten everything.
- Keep your keys and your machine secure. A leaked key = a drained account.

## 5. No guarantees

There is no edge model shipped that is known to be profitable. Pythia gives you the machinery to
express and manage an edge — finding a real one is on you, and most attempts lose money after fees.
