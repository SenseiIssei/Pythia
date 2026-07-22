import { ShieldAlert, Github, BookOpen, Server, Cpu, BrainCircuit, Coffee, Globe } from "lucide-react";
import { Card, PageHeader, Badge } from "../components/ui";
import { aiMode } from "../ai";
import { isTauri } from "../engine";

const REPO = "https://github.com/SenseiIssei/Pythia";
const KOFI = "https://ko-fi.com/senseiissei";

export function About() {
  const runtime = isTauri() ? "Native desktop (Rust engine)" : aiMode() === "server" ? "Web app → backend server" : "Browser paper engine";

  return (
    <div className="animate-fade-in max-w-3xl">
      <PageHeader title="About Pythia" subtitle="Autonomous multi-venue prediction & trading cockpit" />

      <Card className="mb-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 shrink-0 rounded-lg bg-gradient-to-br from-accent to-purple-neon glow-cyan" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 font-bold">
              PYTHIA <Badge tone="cyan">v0.4 · Phase 1+</Badge>
              <Badge tone="purple">{runtime}</Badge>
            </div>
            <div className="text-xs text-cyber-text-dim">
              Polymarket + crypto + equities · one engine core · three runtimes · your choice of AI.
            </div>
          </div>
        </div>
      </Card>

      <Card title="Architecture" className="mb-4" right={<Server size={14} className="text-accent" />}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Pillar icon={Cpu} title="pythia-core" body="One Rust engine crate — strategies, indicators, sovereign risk, connectors, real market data. No UI." />
          <Pillar icon={Server} title="Backend server" body="axum HTTP + WebSocket over the same core, so a web dashboard or phone app share one authoritative brain." />
          <Pillar icon={Globe} title="One UI, 3 runtimes" body="Native (Rust daemon), web (→ backend), or browser paper engine — auto-detected, byte-for-byte in lockstep." />
        </div>
      </Card>

      <Card title="What works today" className="mb-4">
        <ul className="list-inside list-disc space-y-1 text-sm text-cyber-text-dim">
          <li>Runs three ways from one UI: <span className="text-accent">native desktop</span>, <span className="text-accent">web + backend server</span>, and <span className="text-accent">browser paper</span> — identical, verified indicator-for-indicator</li>
          <li>8 strategies: EMA cross, Bollinger, RSI, MACD, Donchian breakout, multi-timeframe momentum, BTC/ETH pairs, Prob-Edge (EWMA fair-value on live odds), plus a rule-based Strategy Composer</li>
          <li>Position management: ATR stop-loss, take-profit &amp; trailing stops (auto-exit)</li>
          <li>Advanced risk: max-drawdown breaker, daily reset, loss-streak cooldowns, fractional-Kelly &amp; volatility-targeted sizing, regime filter, adaptive allocation</li>
          <li>Research suite: backtester, Monte-Carlo optimizer, walk-forward validation, analytics &amp; correlation matrix</li>
          <li><span className="text-accent">AI Signals</span>: bring any API key — Claude, GPT, Grok, GLM, Gemini, DeepSeek, Groq, Mistral, OpenRouter or local Ollama reason over your markets</li>
          <li>Discord/webhook alerts on fills, exits &amp; risk trips; real read-only Kraken + Polymarket data; OS-keychain key storage; persistent state; system tray; first-run legal gate</li>
        </ul>
        <div className="mt-3 text-xs text-cyber-text-faint">
          Next (Phase 2): gated live execution per venue. Real money stays behind your own keys and a per-strategy
          typed confirmation. See PLAN.md.
        </div>
      </Card>

      <Card className="mb-4 border-danger/30 bg-danger/5">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-danger text-glow-red">Not financial advice</div>
            Automated trading and prediction-market betting carry a real risk of losing all committed
            money. Pythia ships in paper mode; going live requires your own API keys and a deliberate
            per-strategy confirmation. AI signals are advisory only — no model reliably predicts prices, and none of
            them place orders. Confirm legality in your jurisdiction (Polymarket is geoblocked for US persons).
            Read <span className="text-accent">SAFETY.md</span> in full.
          </div>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={KOFI}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 rounded-lg border border-purple-neon/40 bg-purple-neon/10 px-3 py-1.5 text-sm font-medium text-purple-neon transition-colors hover:bg-purple-neon/20"
        >
          <Coffee size={14} /> Support on Ko-fi
        </a>
        <a
          href={REPO}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 rounded-lg border border-cyber-border-bright px-3 py-1.5 text-sm text-cyber-text-dim transition-colors hover:border-accent hover:text-accent"
        >
          <Github size={14} /> GitHub
        </a>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><BookOpen size={12} /> PLAN.md</span>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><ShieldAlert size={12} /> SAFETY.md</span>
        <span className="flex items-center gap-1 text-xs text-cyber-text-faint"><BrainCircuit size={12} /> by SenseiIssei</span>
      </div>
    </div>
  );
}

function Pillar({ icon: Icon, title, body }: { icon: typeof Server; title: string; body: string }) {
  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-surface/40 p-3">
      <div className="mb-1 flex items-center gap-1.5 text-sm font-bold text-accent">
        <Icon size={14} /> {title}
      </div>
      <div className="text-xs leading-snug text-cyber-text-dim">{body}</div>
    </div>
  );
}
