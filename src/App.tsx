import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Menu, Minus, X, Power, ShieldCheck, TriangleAlert } from "lucide-react";
import { navFor, isVisible, type PageId } from "./nav";
import { setUiMode, useUiMode, type UiMode } from "./uiMode";
import { Home as HomePage } from "./pages/Home";
import { StoreProvider, useStore } from "./store";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Badge } from "./components/ui";
import { DataHealthBadge } from "./components/DataHealth";
import { isTauri } from "./engine";
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

/** Below this width the sidebar becomes a drawer over the page. */
const NARROW = "(max-width: 767px)";

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(NARROW).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(NARROW);
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    // Sync once: the width may have changed between the first render and now.
    on();
    mq.addEventListener("change", on);
    window.addEventListener("resize", on);
    return () => {
      mq.removeEventListener("change", on);
      window.removeEventListener("resize", on);
    };
  }, []);
  return narrow;
}

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
      <div
        role="status"
        className="flex items-center justify-center gap-2 border-b border-danger/40 bg-danger/10 px-3 py-1.5 text-center font-mono text-xs font-bold text-danger text-glow-red animate-pulse-red"
      >
        <Power size={13} aria-hidden className="shrink-0" />
        {simple ? "Stopped: it will not open anything new" : "Kill switch engaged: live buys halted"}
      </div>
    );
  }
  return (
    <div
      role="status"
      className={`flex items-center justify-center gap-2 border-b px-3 py-1.5 text-center font-mono text-xs font-medium ${
        live
          ? "border-danger/40 bg-danger/10 text-danger animate-pulse-red"
          : "border-success/20 bg-success/[0.06] text-success"
      }`}
    >
      {live ? (
        <TriangleAlert size={13} aria-hidden className="shrink-0" />
      ) : (
        <ShieldCheck size={13} aria-hidden className="shrink-0" />
      )}
      {live
        ? simple
          ? "Real money: this can place real orders"
          : "Live: real orders may be placed"
        : simple
          ? "Practice mode: fake money, nothing can be lost"
          : "Paper mode: simulated money, no orders leave this machine"}
    </div>
  );
}

/**
 * The view switch, at the foot of the sidebar where someone who feels lost (or
 * wants more) will find it without knowing what to look for. Settings has the
 * same switch with a longer explanation.
 */
function ViewSwitch({ mode }: { mode: UiMode }) {
  const options: { id: UiMode; label: string }[] = [
    { id: "simple", label: "Simple" },
    { id: "advanced", label: "Advanced" },
  ];
  return (
    <div className="border-t border-cyber-border p-3">
      <div id="view-switch-label" className="mb-1.5 px-1 font-mono text-[10px] uppercase tracking-widest text-cyber-text-faint">
        View
      </div>
      <div
        role="radiogroup"
        aria-labelledby="view-switch-label"
        className="grid grid-cols-2 gap-0.5 rounded-lg border border-cyber-border-bright bg-cyber-bg/60 p-0.5"
      >
        {options.map((o) => {
          const on = mode === o.id;
          return (
            <button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setUiMode(o.id)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                on ? "bg-accent/15 text-accent" : "text-cyber-text-dim hover:text-cyber-text"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 px-1 text-[11px] leading-snug text-cyber-text-faint">
        {mode === "simple"
          ? "Only the essentials. Advanced adds charts, strategies and risk controls."
          : "Every page and control. Simple keeps only the essentials."}
      </p>
    </div>
  );
}

function Chrome() {
  const [page, setPage] = useState<PageId>("home");
  const narrow = useNarrow();
  const [sidebar, setSidebar] = useState(() => !(window.matchMedia?.(NARROW).matches ?? false));
  const { portfolio, toggleKill, limits } = useStore();
  const mode = useUiMode();
  const mainRef = useRef<HTMLElement>(null);
  const native = isTauri();

  // The drawer starts closed on a phone and open on a desktop, and follows a
  // window that is resized across the line.
  useEffect(() => setSidebar(!narrow), [narrow]);

  // Escape closes the drawer on a phone.
  useEffect(() => {
    if (!narrow || !sidebar) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSidebar(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [narrow, sidebar]);

  const nav = navFor(mode);
  const sections = [...new Set(nav.map((n) => n.section))];
  // Leaving advanced mode while on an advanced page would strand the user on a
  // screen with no way back to it in the sidebar.
  const current = isVisible(page, mode) ? page : "home";
  const live = portfolio.mode === "live";
  const simple = mode === "simple";

  function go(id: PageId) {
    setPage(id);
    if (narrow) setSidebar(false);
    mainRef.current?.scrollTo({ top: 0 });
  }

  const navBody = (
    <div className="flex h-full w-64 flex-col md:w-52">
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {sections.map((section) => (
          <div key={section} className="mb-4">
            <div className="mb-1 px-2 font-mono text-[10px] uppercase tracking-widest text-cyber-text-faint">
              {section}
            </div>
            {nav
              .filter((n) => n.section === section)
              .map((item) => {
                const active = current === item.id;
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => go(item.id)}
                    aria-current={active ? "page" : undefined}
                    className={`relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                      active
                        ? "bg-accent/[0.07] font-medium text-accent"
                        : "text-cyber-text-dim hover:bg-cyber-surface-2 hover:text-cyber-text"
                    }`}
                  >
                    {active && (
                      <motion.div
                        layoutId="sidebar-active"
                        className="absolute left-0 h-6 w-0.5 rounded-full bg-accent glow-cyan"
                      />
                    )}
                    <Icon size={16} aria-hidden />
                    {item.label}
                  </button>
                );
              })}
          </div>
        ))}
      </div>
      <ViewSwitch mode={mode} />
    </div>
  );

  return (
    <div className="app-window grid-bg">
      {/* titlebar */}
      <div className="titlebar flex h-12 shrink-0 items-center justify-between gap-2 border-b border-cyber-border bg-cyber-surface/80 px-2 backdrop-blur-sm sm:px-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setSidebar((s) => !s)}
            aria-label={sidebar ? "Hide the menu" : "Show the menu"}
            aria-expanded={sidebar}
            aria-controls="main-nav"
            className="rounded-md p-1.5 text-cyber-text-dim hover:bg-cyber-surface-2 hover:text-accent"
          >
            <Menu size={18} aria-hidden />
          </button>
          <div className="flex min-w-0 items-center gap-2">
            <div className="h-3 w-3 shrink-0 rounded-full bg-gradient-to-br from-accent to-purple-neon glow-cyan" aria-hidden />
            <span className="font-mono font-bold tracking-widest text-glow-cyan">PYTHIA</span>
            <span className="hidden font-mono text-xs text-cyber-text-faint sm:inline">v0.4</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <DataHealthBadge />
          <Badge
            tone={live ? "red" : "green"}
            title={live ? "Real orders can be placed" : "Simulated money only"}
          >
            {live ? (simple ? "REAL MONEY" : "LIVE") : simple ? "PRACTICE" : "PAPER"}
          </Badge>
          <button
            type="button"
            onClick={toggleKill}
            aria-pressed={limits.killSwitch}
            title={
              limits.killSwitch
                ? "Stopped. Press to let it open new trades again."
                : "Stop it opening anything new, right away. It can still close what it holds."
            }
            className={`flex items-center gap-1 rounded-lg border px-2 py-1 font-mono text-xs font-bold transition-colors ${
              limits.killSwitch
                ? "border-danger/50 bg-danger/20 text-danger glow-red"
                : "border-cyber-border-bright text-cyber-text-dim hover:border-danger/50 hover:text-danger"
            }`}
          >
            <Power size={13} aria-hidden />
            {limits.killSwitch ? "STOPPED" : "KILL"}
          </button>
          {/* Window controls only mean something in the desktop app. */}
          {native && (
            <>
              <button
                type="button"
                onClick={() => void minimizeWindow()}
                aria-label="Minimize"
                title="Minimize"
                className="rounded-md p-1 text-cyber-text-dim hover:text-accent"
              >
                <Minus size={16} aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => void hideWindow()}
                aria-label="Close to tray"
                title="Close to tray (keeps running)"
                className="rounded-md p-1 text-cyber-text-dim hover:text-danger"
              >
                <X size={16} aria-hidden />
              </button>
            </>
          )}
        </div>
      </div>

      <ModeBanner />

      <div className="relative flex min-h-0 flex-1">
        {/* sidebar: a column on a desktop, a drawer over the page on a phone */}
        {narrow ? (
          <AnimatePresence>
            {sidebar && (
              <>
                <motion.div
                  key="scrim"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  onClick={() => setSidebar(false)}
                  className="absolute inset-0 z-30 bg-black/60"
                  aria-hidden
                />
                <motion.nav
                  key="drawer"
                  id="main-nav"
                  aria-label="Pages"
                  initial={{ x: "-100%" }}
                  animate={{ x: 0 }}
                  exit={{ x: "-100%" }}
                  transition={{ type: "tween", duration: 0.2 }}
                  className="absolute inset-y-0 left-0 z-40 border-r border-cyber-border bg-cyber-surface shadow-2xl shadow-black/60"
                >
                  {navBody}
                </motion.nav>
              </>
            )}
          </AnimatePresence>
        ) : (
          <AnimatePresence initial={false}>
            {sidebar && (
              <motion.nav
                id="main-nav"
                aria-label="Pages"
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 208, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                className="shrink-0 overflow-hidden border-r border-cyber-border bg-cyber-surface/50"
              >
                {navBody}
              </motion.nav>
            )}
          </AnimatePresence>
        )}

        {/* page host: all pages mounted, inactive hidden, for instant switching */}
        <main ref={mainRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
          {(Object.keys(PAGES) as PageId[]).map((id) => {
            const Page = PAGES[id];
            return (
              <div
                key={id}
                style={{ display: current === id ? "block" : "none" }}
                className="px-4 pb-10 pt-5 sm:px-6 sm:pt-6"
              >
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
  let body: ReactNode;
  if (!accepted) {
    body = <LegalGate onAccept={() => setAccepted(true)} />;
  } else if (!onboarded) {
    body = <Onboarding onDone={() => setOnboarded(true)} />;
  } else {
    body = (
      <StoreProvider>
        <Chrome />
      </StoreProvider>
    );
  }
  // Framer animations follow the operating system's "reduce motion" setting.
  return <MotionConfig reducedMotion="user">{body}</MotionConfig>;
}
