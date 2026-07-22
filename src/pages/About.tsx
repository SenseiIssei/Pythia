import { Info, ShieldAlert, Github, BookOpen } from "lucide-react";
import { Card, PageHeader, Badge } from "../components/ui";

export function About() {
  return (
    <div className="animate-fade-in max-w-3xl">
      <PageHeader title="About Pythia" subtitle="Autonomous multi-venue prediction & trading cockpit" />

      <Card className="mb-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-accent to-purple-neon glow-cyan" />
          <div>
            <div className="flex items-center gap-2 font-bold">
              PYTHIA <Badge tone="cyan">v0.3 · Phase 1+</Badge>
            </div>
            <div className="text-xs text-cyber-text-dim">
              Polymarket + crypto + equities, one strategy engine, one risk manager, one cockpit.
            </div>
          </div>
        </div>
      </Card>

      <Card title="What works today" className="mb-4">
        <ul className="list-inside list-disc space-y-1 text-sm text-cyber-text-dim">
          <li>Runs two ways from one UI: <span className="text-accent">native desktop app</span> (Rust daemon) and <span className="text-accent">browser/web app</span> (TypeScript) — identical, verified indicator-for-indicator</li>
          <li>8 strategies: EMA cross, Bollinger, RSI, MACD, Donchian breakout, multi-timeframe momentum, BTC/ETH pairs, Prob-Edge (with an EWMA fair-value model on live odds)</li>
          <li>Position management: ATR stop-loss, take-profit & trailing stops (auto-exit)</li>
          <li>Advanced risk: max-drawdown breaker, daily reset, loss-streak cooldowns, fractional-Kelly & volatility-targeted sizing</li>
          <li>Backtester (Sharpe / max-DD / profit factor) + Analytics (drawdown chart, leaderboard, trade log)</li>
          <li>Discord/webhook alerts on fills, exits & risk trips (native)</li>
          <li>Real read-only market data (native): live Kraken crypto + Polymarket odds</li>
          <li>Secure key storage (OS keychain), persistent state, system tray, first-run legal gate</li>
        </ul>
        <div className="mt-3 text-xs text-cyber-text-faint">
          Next (Phase 2): gated live execution per venue, a backtester, and a probability-model
          plug-in for Prob-Edge. See PLAN.md.
        </div>
      </Card>

      <Card className="border-danger/30 bg-danger/5">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-danger text-glow-red">Not financial advice</div>
            Automated trading and prediction-market betting carry a real risk of losing all committed
            money. Pythia ships in paper mode; going live requires your own API keys and a deliberate
            per-strategy confirmation. Confirm legality in your jurisdiction (Polymarket is
            geoblocked for US persons). Read <span className="text-accent">SAFETY.md</span> in full.
          </div>
        </div>
      </Card>

      <div className="mt-4 flex gap-4 text-xs text-cyber-text-faint">
        <span className="flex items-center gap-1"><BookOpen size={12} /> PLAN.md</span>
        <span className="flex items-center gap-1"><ShieldAlert size={12} /> SAFETY.md</span>
        <span className="flex items-center gap-1"><Github size={12} /> SenseiIssei</span>
        <span className="flex items-center gap-1"><Info size={12} /> built with Claude</span>
      </div>
    </div>
  );
}
