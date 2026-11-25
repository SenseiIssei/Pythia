// Startup and idle cost of the built UI, measured headless. The browser build
// runs its own simulated engine, so no server, key or network is needed.
//
//   npm run build && npm run bench:ui
//
// Needs a Chromium: set CHROME_PATH (see scripts/shots.mjs). Prints the median
// of five loads: script bytes, time until the sidebar is there,
// DOM size, and the main-thread time of ten idle seconds (about six ticks).
// BENCH_CPU=4 slows the CPU four times; BENCH_DIST points at another build.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import puppeteer from "puppeteer-core";

const exe = process.env.CHROME_PATH;
if (!exe) {
  console.error("Set CHROME_PATH to a Chromium or Chrome executable.");
  process.exit(1);
}
const RUNS = Number(process.env.BENCH_RUNS ?? 5);
const IDLE_MS = 10_000;
const dist = join(import.meta.dirname, "..", process.env.BENCH_DIST ?? "dist");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".png": "image/png" };

const server = createServer((req, res) => {
  const path = new URL(req.url, "http://x").pathname.slice(1);
  const file = join(dist, normalize(path || "index.html"));
  if (!file.startsWith(dist) || !existsSync(file) || !statSync(file).isFile()) return void res.writeHead(404).end();
  res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ["--no-first-run"] });
const rows = [];
for (let i = 0; i < RUNS; i++) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  if (process.env.BENCH_CPU) await page.emulateCPUThrottling(Number(process.env.BENCH_CPU));
  await page.setViewport({ width: 1240, height: 820 });
  await page.evaluateOnNewDocument(() => {
    for (const [k, v] of Object.entries({ "pythia.legal.ack.v1": "1", "pythia.onboarding.v1": "1" })) localStorage.setItem(k, v);
  });
  let bytes = 0;
  let starting = true;
  page.on("response", async (r) => {
    if (starting && r.request().resourceType() === "script") bytes += (await r.buffer().catch(() => Buffer.alloc(0))).length;
  });
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "load" });
  await page.waitForSelector("nav button", { timeout: 20_000 });
  const ready = Date.now() - t0;
  starting = false; // the other pages' code comes later, in the background
  await new Promise((r) => setTimeout(r, 2_000));
  const m0 = await page.metrics();
  await new Promise((r) => setTimeout(r, IDLE_MS));
  const m1 = await page.metrics();
  rows.push({
    "script kB at start": bytes / 1000,
    "ready ms": ready,
    "startup main-thread ms": m0.TaskDuration * 1000,
    "idle main-thread ms per 10 s": (m1.TaskDuration - m0.TaskDuration) * 1000,
    "of it script ms": (m1.ScriptDuration - m0.ScriptDuration) * 1000,
    "DOM nodes": m1.Nodes,
    "heap MB": m1.JSHeapUsedSize / 1e6,
  });
  await ctx.close();
}
await browser.close();
server.close();

const median = (v) => v.sort((a, b) => a - b)[Math.floor(v.length / 2)];
for (const k of Object.keys(rows[0])) console.log(`${k.padEnd(30)} ${median(rows.map((r) => r[k])).toFixed(0)}`);
