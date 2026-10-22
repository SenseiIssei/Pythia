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

Nobody but you enters your credentials, funds an account, or decides to trade. The software
places orders under your control, with your keys.

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

One exchange key looks like an exception and is not: a **Coinbase** API key comes as a key name plus
an EC private key in PEM form. That private key is the API key's secret, not a wallet key. It is
issued by Coinbase, scoped to the permissions you picked, revocable in the CDP portal at any time,
and it signs API requests only; it controls no funds on any blockchain. Create it with **View** and
**Trade** and never **Transfer**, and give it an **IP allowlist**, so a leaked copy can neither move
money off Coinbase nor be used from another machine. It is stored in the OS keychain like every
other exchange secret and never appears in logs or error messages.

It has **no field that accepts a wallet private key or a seed phrase**, and this is deliberate. On-chain
wallets are watched by *public address* only — Pythia can read the balance and cannot move it. That
is why Polymarket order routing is not implemented: its CLOB is signed with a Polygon private key
rather than a revocable credential, which is a different risk category and needs its own gates. See
`PROFIT-PLAN.md` §7.3.

## 3b-1. The one exception: the pump.fun test wallet on the server

The pump.fun bot cannot trade with an API key: on Solana every trade is signed by a wallet key.
At the owner's explicit request there is exactly one such wallet, with these lines
(`docs/PUMPFUN-LIVE.md`):

- **The owner makes it himself**, interactively on the server, with the lab's wallet tool. It is
  the only code in Pythia that makes a key. The app has no field for it; the key never leaves the
  server, is read only by the live executor's signer at runtime, and is never logged, shown or sent
  (the backup is shown once, on the owner's terminal, after he types YES).
- **Money only comes in from the owner.** He funds it by sending SOL to its address from his own
  wallet or exchange. Nothing in Pythia withdraws or transfers; before signing, the executor refuses
  any instruction that is not a plain pump.fun buy or sale for the wallet itself. He withdraws by
  importing his backup into his own wallet.
- **It is a small, capped test.** At most 2 SOL in all, 0.5 SOL a day, 0.05 SOL a trade (hard in
  code), the owner's written confirmation, a passed mainnet simulation, a kill switch in the app
  that only the server can undo, and a service he starts by hand. Expect to lose all of it.
- **One faster path, the owner's switch.** With `PYTHIA_PUMPFUN_SENDER` set, our own single
  transaction goes out through Helius Sender's stake-weighted path (`swqos_only=true`, never a
  bundle) and carries one tip of at most 0.0001 SOL to one of Sender's ten published tip accounts.
  The executor refuses any other tip, any other Sender route, and a second tip; when Sender does not
  answer, the plain RPC sends the same transaction.

## 3c. Crypto spot is long-only

Spot exchanges cannot short. A strategy emitting a sell signal on an asset you do not hold is
refused at preflight, not sent and rejected. Equity shorts are off by default for the same reason —
they need a margin account, cannot be fractional at Alpaca, and quietly turn a sell signal into a
wall of broker errors.

## 3d. Demo is virtual money, and kept apart

A strategy set to **Demo** sends orders to a venue's demo environment (Bybit Demo
Trading, Binance Spot Demo Mode, OKX demo, Alpaca paper) with **demo keys** stored
in their own slot. It needs no live arm, still passes the risk manager, and its
fills are marked demo everywhere and never written to the tax record. Live keys
are never used for demo orders and demo keys never for live ones. A good demo
record is better evidence than paper, and still not a promise: some demo books are
not the real market (`docs/DEMO.md`).

## 3e. The Autopilot trades an amount, it never moves one

An Autopilot is given an amount and trades it with its strategies until you stop it or one of its
stop rules fires (max loss, take profit, trailing floor, end time). It is an order-placing feature
and nothing more:

- **The money is already at the venue.** The amount lives in an exchange or broker account that
  **you** funded. Pythia has no deposit, withdrawal or transfer function anywhere, and a test checks
  that none appears. Your Exodus wallet (or any other wallet) stays a **watched treasury**: Pythia
  reads its balance by public address and cannot move a coin out of it. Moving money from the wallet
  to an exchange is something you do yourself, deliberately, outside Pythia.
- **Live is gated harder than anything else.** A live autopilot starts only when live routing is
  armed for its venue, every strategy in it has a green Strategy Passport, it has a max-loss rule,
  you typed the confirmation, and its amount fits in the free cash the venue reports (minus what
  other live autopilots there already committed). It never arms anything itself. The one exception
  to the passport is the capped live test below (§3f).
- **It stops safely.** A paused autopilot opens nothing new, but its stop rules still apply. On a
  stop it closes its positions (unless you said not to) and pauses its strategies. If live routing
  is disarmed while it runs, or after a restart, it pauses and says why; real positions it could not
  close stay with it and are closed as soon as routing is back. Its peak and floor are saved, so a
  restart can never reset a stop rule.
- **Demo** mode trades the venue's demo account with demo keys, exactly as a strategy set to Demo
  does (§3d): virtual money through the real API, never in the tax record.

## 3f. Capped live test

A capped live test lets you trade a small amount of real money with a strategy you name (for
example the best lab book) before it has a green Strategy Passport. It is the only way real money
reaches a strategy without one, and it is narrow on purpose:

- **It drops one gate, the passport.** Everything else about live stays: your typed confirmation,
  live routing armed on the Live page, the venue enabled for live, a max-loss rule, the free cash
  read from the venue, the kill switch, reconciliation, the order lifecycle and the maker settings.
  The daily loss breakers of the risk limits still run on its orders, but they measure the paper
  account's equity, not the test's, so they do not protect it: what bounds its loss is its own
  max-loss rule (its floor) and its cap.
- **It always ends in cash.** When a stop rule or its floor stops it, it closes every position it
  holds at the venue, whatever "sell everything when it stops" says: the setting is forced on at
  the start and an edit cannot turn it off, so no real coin is left without anything managing it.
  Only the Stop button lets you choose to keep what it holds.
- **It never holds more than its money.** On a live route the lab's weights are scaled to add up to
  at most 100 %, and every buy is cut so the autopilot's holdings (with its orders still at the
  venue) never exceed its own equity; a buy with no room left is refused and journaled.
- **A sale that empties a holding always goes out.** A coin the lab drops is sold whatever its
  size, down to the smallest order the exchange itself takes (on Kraken the pair's minimum volume);
  a trim too small to send that would leave too little to trade sells the whole holding. A holding
  under the exchange's own minimum cannot be sold at all: it is named once as stuck dust and never
  retried.
- **It is capped.** At most `PYTHIA_LIVE_TEST_MAX_USD` dollars (default 120). The code never allows
  more than 300, whatever the variable says. Its max-loss rule must allow at most 25 % of the
  amount, in % or in dollars. Only one live test runs at a time, and a change to it keeps the same
  caps.
- **You name the strategy.** Pythia never picks one for a test, a test is never a portfolio, and an
  experimental lab book (one that failed the lab's deflation test) stays refused for real money,
  test or not. A book the lab marks as an experiment while it runs pauses the live autopilot (a
  test or not) with the reason on its card and in an alert; it cannot be resumed.
- **It says so everywhere.** You confirm it with its own phrase, `START LIVE TEST`. The journal,
  the autopilot's last action, the alerts and every view of it in the app say LIVE TEST or TEST.
- **It is not evidence.** Its trades never count toward a strategy's passport (the live trade
  count), and the readiness check never judges it. A good test result does not make a strategy
  ready; only the passport and the readiness rule do.
- **It is unproven.** Expect to lose the whole amount.

After a restart a live test comes back paused, like every live autopilot, until you arm live again.
Its strategy stays set to live for it. If you change one of the strategy's parameters, the strategy
goes back to paper and the test pauses; stop it and start a new one.

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
