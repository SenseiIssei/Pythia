#!/usr/bin/env node
// Print the backend's go-live readiness report.
//
// Every way a live run fails silently looks identical from the dashboard — an
// armed engine that places no trades. Live keys pointed at the paper endpoint,
// a market-data feed you aren't subscribed to, an account still onboarding, a
// market that closed forty minutes ago: same symptom, four different fixes.
// This asks the server which one it is.
//
//   npm run server        # in one terminal
//   npm run preflight     # in another
//
// Override the target with PYTHIA_URL (default http://127.0.0.1:8787).

const url = (process.env.PYTHIA_URL ?? "http://127.0.0.1:8787").replace(/\/$/, "");

const c = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  bold: "\x1b[1m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
  cyan: "\x1b[36m",
};

let report;
try {
  const res = await fetch(`${url}/api/preflight`);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);
  report = await res.json();
} catch (err) {
  console.error(`${c.red}Could not reach the Pythia backend at ${url}${c.reset}`);
  console.error(`${c.dim}${err.message}${c.reset}\n`);
  console.error(`Start it with:  ${c.cyan}npm run server${c.reset}`);
  console.error(`Different host/port?  ${c.cyan}PYTHIA_URL=http://host:port npm run preflight${c.reset}`);
  process.exit(2);
}

const endpoint = report.paperEndpoint ? "paper (no real money)" : "LIVE (real money)";
console.log(`\n${c.bold}Pythia preflight${c.reset} ${c.dim}· ${url} · broker endpoint: ${endpoint}${c.reset}\n`);

const width = Math.max(...report.checks.map((x) => x.name.length));
for (const check of report.checks) {
  const mark = check.ok ? `${c.green}  ok  ${c.reset}` : `${c.red} FAIL ${c.reset}`;
  console.log(`${mark} ${check.name.padEnd(width)}  ${c.dim}${check.detail}${c.reset}`);
}

const failed = report.checks.filter((x) => !x.ok);
console.log();
if (report.ready) {
  console.log(`${c.green}${c.bold}All checks passed.${c.reset} Arm from the Live page when you're ready.\n`);
} else {
  console.log(`${c.yellow}${c.bold}${failed.length} check(s) need attention.${c.reset}`);
  console.log(`${c.dim}Paper trading keeps working regardless — these only gate live execution.${c.reset}\n`);
}

// Never fail the shell on an unmet check: "not ready yet" is the normal state
// during setup, and a non-zero exit would make this useless in a loop.
process.exit(0);
