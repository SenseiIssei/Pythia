# Pythia

> Autonomous, multi-venue prediction & trading cockpit — Polymarket + crypto + equities, one neon control panel.

Pythia forms an edge estimate for markets you choose, sizes a bet/trade with a disciplined risk
model, and — only when you explicitly arm a strategy — routes real orders. **It ships in paper mode.**

**Before anything live, read [`SAFETY.md`](SAFETY.md) and the [`PLAN.md`](PLAN.md).** Automated
trading and prediction betting can lose all your money. This is not financial advice.

## Stack

Tauri v2 · React 19 · TypeScript · Vite · Tailwind (cyber-neon) · framer-motion · Rust engine core.

## Run it

**One UI, two runtimes.** The same cockpit runs as a native desktop app (Rust engine daemon) or in
the browser (TypeScript engine). It auto-detects which and wires itself up — you don't choose.

**Native desktop app** (recommended — this is where the *real read-only market data* lives):

```bash
npm install
npm run tauri dev     # dev window with hot-reload (needs the Rust toolchain)
npm run tauri build   # produces a Windows installer + Pythia.exe
                      #   → src-tauri/target/release/bundle/nsis/
```

The native build runs a persistent Rust engine that fetches **live Kraken crypto prices** and
**Polymarket odds** (read-only, no keys) and paper-trades against them.

**Browser / web app** (no Rust, no keys — great for exploring the UI):

```bash
npm run dev           # opens the cockpit at http://localhost:5174, paper mode
```

> Windows Rust build note: if `cargo` fails with `failed to find tool "C:\Program"`, unset the
> machine `CC`/`CXX` env vars for the build: `unset CC CXX CFLAGS CXXFLAGS` (they contain spaces
> that break `cc-rs`).

## Modes

- **Paper (default):** a simulated matching engine fills orders against live/replayed prices with a
  fake balance. Prove strategies here first.
- **Live (gated):** requires your own API keys (stored in the OS keychain) and a per-strategy,
  typed confirmation to arm. The global kill switch and risk limits always apply.

## Layout

```
Pythia/
├─ PLAN.md            # the master plan
├─ SAFETY.md          # read before going live
├─ src/               # React cockpit (runs in browser via the paper engine)
│  ├─ engine/         # client-side paper engine + risk + strategies (TS mirror of the Rust core)
│  ├─ pages/          # Dashboard, Markets, Positions, Strategies, Risk, Journal, Settings, About
│  └─ components/     # neon UI kit
└─ src-tauri/         # Rust engine core + Tauri shell (Phase 1)
   └─ src/
      ├─ engine/      # portfolio, risk, strategy runtime
      └─ connectors/  # paper, polymarket, crypto, alpaca
```

See [`PLAN.md`](PLAN.md) for the full architecture and roadmap.
