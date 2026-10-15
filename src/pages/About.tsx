import { ShieldAlert, Github, BookOpen, Server, Cpu, BrainCircuit, Coffee, Globe, ExternalLink, type LucideIcon } from "lucide-react";
import { List, ListRow, Notice, Page } from "../design";
import { Row, Section } from "../pagekit";
import { aiMode } from "../ai";
import { isTauri } from "../engine";

const REPO = "https://github.com/SenseiIssei/Pythia";
const KOFI = "https://ko-fi.com/senseiissei";

const PILLARS: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Cpu, title: "pythia-core", body: "One Rust engine crate: strategies, indicators, sovereign risk, connectors, real market data. No UI." },
  { icon: Server, title: "Backend server", body: "axum HTTP + WebSocket over the same core, so a web dashboard or phone app share one authoritative brain." },
  { icon: Globe, title: "One UI, 3 runtimes", body: "Native (Rust daemon), web (→ backend), or browser paper engine. Auto-detected, byte-for-byte in lockstep." },
];

const WORKS: { title: string; body: string }[] = [
  {
    title: "Runs three ways from one UI",
    body: "Native desktop, web + backend server, and browser paper, identical and verified indicator-for-indicator.",
  },
  {
    title: "8 strategies",
    body: "EMA cross, Bollinger, RSI, MACD, Donchian breakout, multi-timeframe momentum, BTC/ETH pairs, Prob-Edge (EWMA fair-value on live odds), plus a rule-based Strategy Composer.",
  },
  { title: "Position management", body: "ATR stop-loss, take-profit and trailing stops (auto-exit)." },
  {
    title: "Advanced risk",
    body: "Max-drawdown breaker, daily reset, loss-streak cooldowns, fractional-Kelly and volatility-targeted sizing, regime filter, adaptive allocation.",
  },
  { title: "Research suite", body: "Backtester, Monte-Carlo optimizer, walk-forward validation, analytics and correlation matrix." },
  {
    title: "AI Signals",
    body: "Bring any API key (Anthropic, GPT, Grok, GLM, Gemini, DeepSeek, Groq, Mistral, OpenRouter or local Ollama) and let it reason over your markets.",
  },
  {
    title: "Alerts, data and safety",
    body: "Discord/webhook alerts on fills, exits and risk trips; real read-only Kraken + Polymarket data; OS-keychain key storage; persistent state; system tray; first-run legal gate.",
  },
];

export function About() {
  const runtime = isTauri() ? "Native desktop (Rust engine)" : aiMode() === "server" ? "Web app → backend server" : "Browser paper engine";

  return (
    <Page
      title="About Pythia"
      subtitle="A trading cockpit that watches prediction markets, crypto and US shares, practises with fake money, and only trusts what it has proven."
    >
      <Section title="This copy" hint="Which version you run and how it is connected." help="The version and how this copy of Pythia runs.">
        <List>
          <Row label="Version" value="v0.4" valueSub="Phase 1+" help="The app version and the phase of the plan it has reached." />
          <Row label="Running as" value={runtime} help="Where the engine runs: the desktop app, a server, or inside this browser." />
          <Row label="Markets" value="Polymarket, crypto, equities" help="The kinds of markets Pythia watches and trades." />
          <Row label="Built as" value="One engine, three runtimes" sub="and your choice of AI" help="One engine core that runs on the desktop, on a server or in the browser." />
        </List>
      </Section>

      <Section title="Architecture" hint="One engine, shared by every way of running it." help="How the pieces of Pythia fit together.">
        <List>
          {PILLARS.map((p) => (
            <ListRow key={p.title} icon={p.icon} title={p.title} subtitle={p.body} />
          ))}
        </List>
      </Section>

      <Section title="What works today" hint="Everything listed here is built and in use." help="The features that are finished and working now.">
        <List>
          {WORKS.map((w) => (
            <div key={w.title} className="py-3">
              <div className="text-[15px] font-semibold text-ink">{w.title}</div>
              <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{w.body}</p>
            </div>
          ))}
        </List>
        <p className="mt-3 border-t border-line pt-3 text-[13px] leading-relaxed text-muted">
          Next (Phase 2): gated live execution per venue. Real money stays behind your own keys and a per-strategy typed
          confirmation. See PLAN.md.
        </p>
      </Section>

      <Notice tone="danger" icon={ShieldAlert} title="Not financial advice">
        Automated trading and prediction-market betting carry a real risk of losing all committed money. Pythia ships in
        paper mode; going live requires your own API keys and a deliberate per-strategy confirmation. AI signals are
        advisory only: no model reliably predicts prices, and none of them place orders. Confirm legality in your
        jurisdiction (Polymarket is geoblocked for US persons). Read <b>SAFETY.md</b> in full.
      </Notice>

      <Section title="Links" hint="Where the code lives, and how to support the project." help="The project's code, its documents and how to support it.">
        <List>
          <LinkRow href={KOFI} icon={Coffee} title="Support on Ko-fi" sub="Keeps the project going" />
          <LinkRow href={REPO} icon={Github} title="GitHub" sub="The source code" />
          <ListRow icon={BookOpen} title="PLAN.md" subtitle="The roadmap, in the repository" />
          <ListRow icon={ShieldAlert} title="SAFETY.md" subtitle="What can go wrong, and how Pythia guards against it" />
          <ListRow icon={BrainCircuit} title="by SenseiIssei" subtitle="Author" />
        </List>
      </Section>
    </Page>
  );
}

/** A row that opens a web page in a new tab. */
function LinkRow({ href, icon: Icon, title, sub }: { href: string; icon: LucideIcon; title: string; sub: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="-mx-2 flex items-center gap-3 rounded-control px-2 py-3.5 transition-colors hover:bg-surface-2"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-ink" aria-hidden>
        <Icon size={18} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-semibold text-accent">{title}</span>
        <span className="block text-[13px] text-muted">{sub}</span>
      </span>
      <ExternalLink size={16} aria-hidden className="shrink-0 text-faint" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}
