#!/usr/bin/env node
// Walk-forward validate every shipped strategy on real daily candles.
//
//   npm run server      # in one terminal
//   npm run validate    # in another
//
// Every number printed here comes from OUT-OF-SAMPLE bars: parameters were
// fitted on earlier data and scored only on what came after. Expect most
// strategies to fail — that is the harness working, not a bug.
//
// Options:
//   PYTHIA_URL=http://host:port   target a different backend
//   FOLDS=6                       more, shorter out-of-sample windows
//   FRICTIONLESS=1                zero fees/slippage, to size the cost drag
//   COST_MULT=2                   scale the cost model (config/costs.json)

const base = (process.env.PYTHIA_URL ?? "http://127.0.0.1:8787").replace(/\/$/, "");
const folds = process.env.FOLDS ?? "4";
const frictionless = process.env.FRICTIONLESS === "1";
const costMult = frictionless ? "0" : process.env.COST_MULT ?? "1";

const c = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  bold: "\x1b[1m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
  cyan: "\x1b[36m",
};

const params = new URLSearchParams({ folds, costMult });

const url = `${base}/api/research/validate?${params}`;
console.log(`${c.dim}Fetching candles and walking forward — this takes a minute…${c.reset}`);

let data;
try {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);
  data = await res.json();
} catch (err) {
  console.error(`\n${c.red}Could not reach the Pythia backend at ${base}${c.reset}`);
  console.error(`${c.dim}${err.message}${c.reset}\n`);
  console.error(`Start it with:  ${c.cyan}npm run server${c.reset}`);
  process.exit(2);
}

const pct = (x) => `${(x * 100).toFixed(1)}%`;
const sign = (x) => (x >= 0 ? c.green : c.red);

console.log(`\n${c.bold}Walk-forward validation${c.reset} ${c.dim}· ${data.timeframe} bars · ${data.folds} folds${c.reset}`);
console.log(
  `${c.dim}${data.cryptoMarkets} crypto markets (${data.cryptoBars} bars), ` +
    `${data.equityMarkets} equity markets (${data.equityBars} bars) · ` +
    `costs: ${data.costs.cryptoVenue} ${data.costs.crypto.takerBps}bps taker + ` +
    `${data.costs.crypto.halfSpreadBps}bps half-spread per side (majors are tighter), ` +
    `equities ${data.costs.equities.halfSpreadBps}bps half-spread · x${data.costs.costMult}${c.reset}\n`
);

const badge = {
  pass: `${c.green}  PASS  ${c.reset}`,
  marginal: `${c.yellow}MARGINAL${c.reset}`,
  fail: `${c.red}  FAIL  ${c.reset}`,
  insufficient: `${c.dim}NO DATA ${c.reset}`,
};

for (const r of data.reports) {
  const p = r.portfolio;
  console.log(`${badge[r.verdict] ?? r.verdict}  ${c.bold}${r.name}${c.reset}`);
  console.log(
    `          ${c.dim}OOS${c.reset} ${sign(p.totalReturn)}${pct(p.totalReturn)}${c.reset}` +
      `  ${c.dim}Sharpe${c.reset} ${p.sharpe.toFixed(2)}` +
      `  ${c.dim}maxDD${c.reset} ${pct(p.maxDrawdown)}` +
      `  ${c.dim}trades${c.reset} ${p.trades}` +
      `  ${c.dim}win${c.reset} ${pct(p.winRate)}` +
      `  ${c.dim}DSR${c.reset} ${(r.deflatedSharpe * 100).toFixed(0)}%`
  );
  console.log(`          ${c.dim}${r.reason}${c.reset}\n`);
}

if (data.skipped?.length) {
  console.log(`${c.dim}Not scored:${c.reset}`);
  for (const s of data.skipped) {
    console.log(`  ${c.dim}· ${s.name} — ${s.reason}${c.reset}`);
  }
  console.log();
}

console.log(
  `${c.dim}DSR = probability the out-of-sample Sharpe is real rather than the best of the\n` +
    `parameter sets tried. Below 95% the result is not distinguishable from a lucky search.${c.reset}\n`
);

process.exit(0);
