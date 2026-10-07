import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Menu, Minus, X, Power } from "lucide-react";
import { navFor, isVisible, type PageId } from "./nav";
import { useUiMode } from "./uiMode";
import { Home as HomePage } from "./pages/Home";
import { StoreProvider, useStore } from "./store";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Badge } from "./components/ui";
import { minimizeWindow, hideWindow } from "./window";
import { LegalGate, hasAcceptedLegal } from "./components/LegalGate";
import { Onboarding, hasSeenOnboarding } from "./components/Onboarding";
import { Dashboard } from "./pages/Dashboard";
import { Markets } from "./pages/Markets";
import { Positions } from "./pages/Positions";
import { Wallets } from "./pages/Wallets";
import { Strategies } from "./pages/Strategies";
import { Composer } from "./pages/Composer";
import { Backtest } from "./pages/Backtest";
import { Optimizer } from "./pages/Optimizer";
import { Analytics } from "./pages/Analytics";
import { Correlation } from "./pages/Correlation";
import { Signals } from "./pages/Signals";
import { Predictions } from "./pages/Predictions";
import { Models } from "./pages/Models";
import { Lab } from "./pages/Lab";
import { Live } from "./pages/Live";
import { Risk } from "./pages/Risk";
import { Journal } from "./pages/Journal";
import { Settings } from "./pages/Settings";
import { About } from "./pages/About";

const PAGES: Record<PageId, () => ReactNode> = {
  home: HomePage,
  dashboard: Dashboard,
  markets: Markets,
  positions: Positions,
  wallets: Wallets,
  strategies: Strategies,
  composer: Composer,
  backtest: Backtest,
  optimizer: Optimizer,
  analytics: Analytics,
  correlation: Correlation,
  signals: Signals,
  predictions: Predictions,
  models: Models,
  lab: Lab,
  live: Live,
  risk: Risk,
  journal: Journal,
  settings: Settings,
  about: About,
};

/**
 * Always visible, in both modes. Simple mode changes the *words*, never the
 * warning: hiding whether real money is in play would be the one thing a
 * beginner-friendly view must never do.
 */
function ModeBanner() {
  const { portfolio, limits } = useStore();
  const mode = useUiMode();
  const simple = mode === "simple";
  const live = portfolio.mode === "live";

  if (limits.killSwitch) {
    return (
      <div className="flex items-center justify-center gap-2 border-b border-danger/40 bg-danger/10 py-1 text-xs font-bold text-danger text-glow-red animate-pulse-red">
        <Power size={13} />
        {simple ? "STOPPED — it will not open anything new" : "KILL SWITCH ENGAGED — live buys halted"}
      </div>
    );
  }
  return (
    <div
      className={`flex items-center justify-center gap-2 border-b py-1 text-xs font-medium ${
        live
          ? "border-danger/40 bg-danger/10 text-danger animate-pulse-red"
          : "border-accent/20 bg-accent/5 text-accent"
      }`}
    >
      <Activity size={12} />
      {live
        ? simple
          ? "REAL MONEY — this can place real orders"
          : "LIVE — real orders may be placed"
        : simple
          ? "PRACTICE MODE — fake money, nothing can be lost"
          : "PAPER MODE — simulated money, no orders leave this machine"}
    </div>
  );
}

function Chrome() {
  const [page, setPage] = useState<PageId>("home");
  const [sidebar, setSidebar] = useState(true);
  const { portfolio, toggleKill, limits } = useStore();
  const mode = useUiMode();

  const nav = navFor(mode);
  const sections = [...new Set(nav.map((n) => n.section))];
  // Leaving advanced mode while on an advanced page would strand the user on a
  // screen with no way back to it in the sidebar.
  const current = isVisible(page, mode) ? page : "home";

  return (
    <div className="app-window grid-bg">
      {/* titlebar */}
      <div className="titlebar flex h-11 items-center justify-between border-b border-cyber-border bg-cyber-surface/80 px-3 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSidebar((s) => !s)}
            className="rounded p-1 text-cyber-text-dim hover:text-accent"
          >
            <Menu size={16} />
          </button>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-gradient-to-br from-accent to-purple-neon glow-cyan" />
            <span className="font-bold tracking-widest text-glow-cyan">PYTHIA</span>
            <span className="text-xs text-cyber-text-faint">v0.4</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={portfolio.mode === "live" ? "red" : "cyan"}>
            {portfolio.mode === "live" ? "LIVE" : "PAPER"}
          </Badge>
          <button
            onClick={toggleKill}
            title="Global kill switch"
            className={`rounded-lg border px-2 py-1 text-xs font-bold transition-colors ${
              limits.killSwitch
                ? "border-danger/50 bg-danger/20 text-danger glow-red"
                : "border-cyber-border-bright text-cyber-text-dim hover:border-danger/50 hover:text-danger"
            }`}
          >
            <Power size={13} className="inline" /> KILL
          </button>
          <button
            onClick={() => void minimizeWindow()}
            title="Minimize"
            className="rounded p-1 text-cyber-text-dim hover:text-accent"
          >
            <Minus size={16} />
          </button>
          <button
            onClick={() => void hideWindow()}
            title="Close to tray"
            className="rounded p-1 text-cyber-text-dim hover:text-danger"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      <ModeBanner />

      <div className="flex min-h-0 flex-1">
        {/* sidebar */}
        <AnimatePresence initial={false}>
          {sidebar && (
            <motion.nav
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 208, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              className="shrink-0 overflow-hidden border-r border-cyber-border bg-cyber-surface/50"
            >
              <div className="w-52 p-3">
                {sections.map((section) => (
                  <div key={section} className="mb-4">
                    <div className="mb-1 px-2 text-[10px] uppercase tracking-widest text-cyber-text-faint">
                      {section}
                    </div>
                    {nav.filter((n) => n.section === section).map((item) => {
                      const active = current === item.id;
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          onClick={() => setPage(item.id)}
                          className={`relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                            active
                              ? "text-accent text-glow-cyan"
                              : "text-cyber-text-dim hover:bg-cyber-surface-2 hover:text-cyber-text"
                          }`}
                        >
                          {active && (
                            <motion.div
                              layoutId="sidebar-active"
                              className="absolute left-0 h-6 w-0.5 rounded-full bg-accent glow-cyan"
                            />
                          )}
                          <Icon size={16} />
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </motion.nav>
          )}
        </AnimatePresence>

        {/* page host — all pages mounted, inactive hidden, for instant switching */}
        <main className="min-h-0 flex-1 overflow-y-auto">
          {(Object.keys(PAGES) as PageId[]).map((id) => {
            const Page = PAGES[id];
            return (
              <div key={id} style={{ display: current === id ? "block" : "none" }} className="p-6">
                <ErrorBoundary>
                  <Page />
                </ErrorBoundary>
              </div>
            );
          })}
        </main>
      </div>
    </div>
  );
}

export function App() {
  const [accepted, setAccepted] = useState(hasAcceptedLegal());
  const [onboarded, setOnboarded] = useState(hasSeenOnboarding());
  if (!accepted) {
    return <LegalGate onAccept={() => setAccepted(true)} />;
  }
  if (!onboarded) {
    return <Onboarding onDone={() => setOnboarded(true)} />;
  }
  return (
    <StoreProvider>
      <Chrome />
    </StoreProvider>
  );
}
