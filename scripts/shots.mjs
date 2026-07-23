// Headless screenshot capture for the README.
// Uses the system Microsoft Edge via puppeteer-core (no chromium download).
// Run against the dev server (paper or server mode); see scripts note in README.
import puppeteer from "puppeteer-core";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A Chromium binary. Playwright's cached chromium launches headless reliably on
// Windows where Edge hands off to a running instance. Override with CHROME_PATH.
const EDGE =
  process.env.CHROME_PATH ||
  "C:/Users/super/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";
const BASE = process.env.SHOT_URL || "http://localhost:5174";
const OUT = "docs/screenshots";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PAGES = [
  ["dashboard", "Dashboard"],
  ["markets", "Markets"],
  ["strategies", "Strategies"],
  ["composer", "Composer"],
  ["optimizer", "Optimizer"],
  ["analytics", "Analytics"],
  ["correlation", "Correlation"],
  ["signals", "AI Signals"],
  ["live", "Live"],
  ["risk", "Risk"],
  ["settings", "Settings"],
  ["about", "About"],
];

async function goto(page, label) {
  await page.evaluate((lbl) => {
    const b = [...document.querySelectorAll("nav button")].find(
      (x) => x.textContent.trim() === lbl
    );
    if (b) b.click();
  }, label);
  await sleep(1400);
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const profile = mkdtempSync(join(tmpdir(), "pythia-shot-"));
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: "new",
    userDataDir: profile, // dedicated profile so Edge doesn't hand off to a running instance
    args: [
      "--no-sandbox",
      "--disable-gpu",
      "--force-color-profile=srgb",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
    ],
    defaultViewport: { width: 1480, height: 940, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();
  // Skip the first-run legal gate.
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("pythia.legal.ack.v1", "1");
    } catch {}
  });
  await page.goto(BASE, { waitUntil: "networkidle2", timeout: 60000 });

  // Let the engine tick so equity curve, positions and journal fill in.
  console.log("warming up (letting strategies trade)…");
  await sleep(38000);

  for (const [file, label] of PAGES) {
    await goto(page, label);
    await page.screenshot({ path: `${OUT}/${file}.png` });
    console.log("captured", file);
  }

  await browser.close();
  console.log("done →", OUT);
};

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
