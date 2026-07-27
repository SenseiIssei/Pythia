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
3. You arm live execution **per venue** with a typed `ARM LIVE` confirmation. Arming runs a
   read-only credential check first and refuses if a venue does not answer — so a wrong key surfaces
   before an order exists, not after.
4. A strategy still has to be set to **Live** individually before it sends anything.
5. The **risk manager** sits above every live order (kill switch, daily-loss cap, size caps), and the
   venue connector refuses orders that cannot fill (market closed, no buying power, would open a
   short) *before* submitting them.

Claude (the assistant that built this) **never** enters your credentials, never funds an account,
and never executes a trade for you. The software does it, under your control, with your keys.

## 3a. Real positions are not simulated positions

A position opened with a real venue fill is tagged **REAL** and behaves differently from a paper one:

- The simulator will **never** close it. If a stop-loss fires while live routing is disarmed, Pythia
  refuses to book a fake exit and says so in the journal — because telling you that you are flat
  while real shares sit at a broker is the worst thing this software could do.
- **Disarming does not flatten anything.** New orders stop; existing real positions stay open at the
  venue, unmanaged, until you re-arm or close them there. The Live and Positions pages both say so
  while any real position is open.
- The flag survives restarts, and the daemon reconciles against the venue's own position list on
  boot and every couple of minutes. If the two disagree, **the venue wins** and the correction is
  journaled.

## 3b. Keys, wallets, and the line between them

Pythia only ever trades against **revocable, permission-scoped API keys**. Grant them *trade*
permission and **not** withdrawal: then the worst case from a compromised machine is unwanted trades,
not a drained account.

It has **no field that accepts a private key or a seed phrase**, and this is deliberate. On-chain
wallets are watched by *public address* only — Pythia can read the balance and cannot move it. That
is why Polymarket order routing is not implemented: its CLOB is signed with a Polygon private key
rather than a revocable credential, which is a different risk category and needs its own gates. See
`PROFIT-PLAN.md` §7.3.

## 3c. Crypto spot is long-only

Spot exchanges cannot short. A strategy emitting a sell signal on an asset you do not hold is
refused at preflight, not sent and rejected. Equity shorts are off by default for the same reason —
they need a margin account, cannot be fractional at Alpaca, and quietly turn a sell signal into a
wall of broker errors.

## 4. Your responsibilities

- Test every strategy in paper for long enough to trust it. A good paper result is necessary, not
  sufficient — slippage, fees, and thin liquidity make live worse than paper.
- Set the risk limits **before** arming anything live. Start tiny.
- Keep the kill switch reachable. Know how to flatten everything.
- Keep your keys and your machine secure. A leaked key = a drained account.

## 5. No guarantees

There is no edge model shipped that is known to be profitable. Pythia gives you the machinery to
express and manage an edge — finding a real one is on you, and most attempts lose money after fees.

The shipped strategies are textbook indicators. Anything that well known has been arbitraged for
decades; what remains of it is easily given back in trading costs. [`PROFIT-PLAN.md`](PROFIT-PLAN.md)
sets out honestly where an edge could actually come from, what a strategy has to prove before it
deserves real money, and the arithmetic that makes high-turnover bots lose. Read it before you
believe a backtest.
