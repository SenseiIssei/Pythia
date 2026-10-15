import { ShieldAlert, Github, BookOpen, Server, Cpu, BrainCircuit, Coffee, Globe } from "lucide-react";
import { Card, Badge } from "../components/ui";
import { Notice, Page } from "../design";
import { aiMode } from "../ai";
import { isTauri } from "../engine";

const REPO = "https://github.com/SenseiIssei/Pythia";
const KOFI = "https://ko-fi.com/senseiissei";

export function About() {
  const runtime = isTauri() ? "Native desktop (Rust engine)" : aiMode() === "server" ? "Web app → backend server" : "Browser paper engine";

  return (
    <Page
      title="About Pythia"
      subtitle="A trading cockpit that watches prediction markets, crypto and US shares, practises with fake money, and only trusts what it has proven."
    >
      <Card>
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-lg font-bold text-on-primary" aria-hidden>P</div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 font-bold">
              Pythia <Badge tone="neutral">v0.4 · Phase 1+</Badge>
              <Badge tone="purple">{runtime}</Badge>
            </div>
            <div className="mt-0.5 text-[13px] text-muted">
              Polymarket + crypto + equities · one engine core · three runtimes · your choice of AI.
            </div>
          </div>
        </div>
      </Card>

      <Card title="Architecture">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Pillar icon={Cpu} title="pythia-core" body="One Rust engine crate: strategies, indicators, sovereign risk, connectors, real market data. No UI." />
          <Pillar icon={Server} title="Backend server" body="axum HTTP + WebSocket over the same core, so a web dashboard or phone app share one authoritative brain." />
          <Pillar icon={Globe} title="One UI, 3 runtimes" body="Native (Rust daemon), web (→ backend), or browser paper engine. Auto-detected, byte-for-byte in lockstep." />
        </div>
      </Card>

      <Card title="What works today">
        <ul className="list-outside list-disc space-y-1.5 pl-5 text-[15px] leading-relaxed text-muted">
          <li>Runs three ways from one UI: <span className="font-medium text-ink">native desktop</span>, <span className="font-medium text-ink">web + backend server</span>, and <span className="font-medium text-ink">browser paper</span>, identical and verified indicator-for-indicator</li>
          <li>8 strategies: EMA cross, Bollinger, RSI, MACD, Donchian breakout, multi-timeframe momentum, BTC/ETH pairs, Prob-Edge (EWMA fair-value on live odds), plus a rule-based Strategy Composer</li>
          <li>Position management: ATR stop-loss, take-profit &amp; trailing stops (auto-exit)</li>
          <li>Advanced risk: max-drawdown breaker, daily reset, loss-streak cooldowns, fractional-Kelly &amp; volatility-targeted sizing, regime filter, adaptive allocation</li>
          <li>Research suite: backtester, Monte-Carlo optimizer, walk-forward validation, analytics &amp; correlation matrix</li>
          <li><span className="font-medium text-ink">AI Signals</span>: bring any API key (Claude, GPT, Grok, GLM, Gemini, DeepSeek, Groq, Mistral, OpenRouter or local Ollama) and let it reason over your markets</li>
          <li>Discord/webhook alerts on fills, exits &amp; risk trips; real read-only Kraken + Polymarket data; OS-keychain key storage; persistent state; system tray; first-run legal gate</li>
        </ul>
        <div className="mt-3 text-[13px] text-faint">
          Next (Phase 2): gated live execution per venue. Real money stays behind your own keys and a per-strategy
          typed confirmation. See PLAN.md.
        </div>
      </Card>

      <Notice tone="danger" title="Not financial advice">
            Automated trading and prediction-market betting carry a real risk of losing all committed
            money. Pythia ships in paper mode; going live requires your own API keys and a deliberate
            per-strategy confirmation. AI signals are advisory only: no model reliably predicts prices, and none of
            them place orders. Confirm legality in your jurisdiction (Polymarket is geoblocked for US persons).
            Read <span className="font-medium text-ink">SAFETY.md</span> in full.
      </Notice>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={KOFI}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-semibold text-on-primary transition-opacity hover:opacity-90"
        >
          <Coffee size={14} /> Support on Ko-fi
        </a>
        <a
          href={REPO}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full bg-surface-2 px-4 text-sm font-semibold text-ink transition-colors hover:bg-line"
        >
          <Github size={14} /> GitHub
        </a>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><BookOpen size={12} /> PLAN.md</span>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><ShieldAlert size={12} /> SAFETY.md</span>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><BrainCircuit size={12} /> by SenseiIssei</span>
      </div>
    </Page>
  );
}

function Pillar({ icon: Icon, title, body }: { icon: typeof Server; title: string; body: string }) {
  return (
    <div className="rounded-2xl bg-surface-2 p-4">
      <div className="mb-1 flex items-center gap-2 text-[15px] font-semibold text-ink">
        <Icon size={16} aria-hidden className="text-muted" /> {title}
      </div>
      <div className="text-[13px] leading-snug text-muted">{body}</div>
    </div>
  );
}
