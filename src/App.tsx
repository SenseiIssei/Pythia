import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Menu, Minus, Moon, PanelLeft, Power, ShieldCheck, Sun, TriangleAlert, X } from "lucide-react";
import { activeTab, navFor, isVisible, resolvePage, tabsFor, type PageId } from "./nav";
import { onOpenPage } from "./navigate";
import { Segmented, TabBar } from "./design";
import { setThemePref, useTheme } from "./design/theme";
import { setUiMode, useUiMode, type UiMode } from "./uiMode";
import { Home as HomePage } from "./pages/Home";
import { StoreProvider, useStore } from "./store";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DataHealthBadge } from "./components/DataHealth";
import { isTauri } from "./engine";
import { minimizeWindow, hideWindow } from "./window";
import { LegalGate, hasAcceptedLegal } from "./components/LegalGate";
import { Onboarding, hasSeenOnboarding } from "./components/Onboarding";
import { Autopilots } from "./pages/Autopilots";
import { Activity } from "./pages/Activity";
import { Notifications } from "./pages/Notifications";
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
import { Cards } from "./pages/Cards";
import { Research } from "./pages/Research";
import { Live } from "./pages/Live";
import { Risk } from "./pages/Risk";
import { Journal } from "./pages/Journal";
import { Settings } from "./pages/Settings";
import { About } from "./pages/About";

// "practice" is not a page of its own any more: resolvePage sends it to the
// Autopilot page, which shows what Practice showed.
const PAGES: Record<Exclude<PageId, "practice">, () => ReactNode> = {
  home: HomePage,
  autopilot: Autopilots,
  activity: Activity,
  notifications: Notifications,
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
  cards: Cards,
  research: Research,
  live: Live,
  risk: Risk,
  journal: Journal,
  settings: Settings,
  about: About,
};

/** Below this width the sidebar becomes a drawer and the phone tab bar shows. */
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
 * A strip under the top bar, only when it matters: real money, or the kill
 * switch. Practice mode is said by the pill in the top bar, on every page.
 * Simple mode changes the words, never the warning.
 */
function ModeBanner() {
  const { portfolio, limits } = useStore();
  const simple = useUiMode() === "simple";
  const live = portfolio.mode === "live";

  if (limits.killSwitch) {
    return (
      <div role="status" className="flex items-center justify-center gap-2 bg-down/10 px-3 py-2 text-center text-[13px] font-semibold text-down">
        <Power size={14} aria-hidden className="shrink-0" />
        {simple ? "Stopped: it will not open anything new" : "Kill switch engaged: live buys halted"}
      </div>
    );
  }
  if (!live) return null;
  return (
    <div role="status" className="flex items-center justify-center gap-2 bg-down px-3 py-2 text-center text-[13px] font-semibold text-on-down">
      <TriangleAlert size={14} aria-hidden className="shrink-0" />
      {simple ? "Real money: this can place real orders" : "Live: real orders may be placed"}
    </div>
  );
}

/** Practice or real money, always in the top bar. */
function ModePill() {
  const { portfolio } = useStore();
  const simple = useUiMode() === "simple";
  const live = portfolio.mode === "live";
  return (
    <span
      role="status"
      title={live ? "Real orders can be placed" : "Simulated money only. Nothing can be lost."}
      className={`inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[13px] font-semibold ${
        live ? "bg-down text-on-down" : "bg-up/10 text-up"
      }`}
    >
      {live ? <TriangleAlert size={14} aria-hidden /> : <ShieldCheck size={14} aria-hidden />}
      {live ? (simple ? "Real money" : "Live") : simple ? "Practice" : "Paper"}
    </span>
  );
}

function StopButton() {
  const { toggleKill, limits } = useStore();
  const on = limits.killSwitch;
  return (
    <button
      type="button"
      onClick={toggleKill}
      aria-pressed={on}
      title={on ? "Stopped. Press to let it open new trades again." : "Stop it opening anything new, right away. It can still close what it holds."}
      className={`inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[13px] font-semibold transition-colors ${
        on ? "bg-down text-on-down" : "bg-surface-2 text-ink hover:bg-down/10 hover:text-down"
      }`}
    >
      <Power size={14} aria-hidden />
      {on ? "Stopped" : "Stop"}
    </button>
  );
}

function ThemeButton() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => setThemePref(next)}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {theme === "dark" ? <Sun size={17} aria-hidden /> : <Moon size={17} aria-hidden />}
    </button>
  );
}

/**
 * The view switch, at the foot of the sidebar where someone who feels lost (or
 * wants more) will find it without knowing what to look for. Settings has the
 * same switch with a longer explanation.
 */
function ViewSwitch({ mode }: { mode: UiMode }) {
  return (
    <div className="border-t border-line p-4">
      <Segmented<UiMode>
        label="View"
        value={mode}
        onChange={setUiMode}
        options={[
          { id: "simple", label: "Simple" },
          { id: "advanced", label: "Advanced" },
        ]}
      />
      <p className="mt-2 px-1 text-[12px] leading-snug text-faint">
        {mode === "simple" ? "Only the essentials. Advanced adds charts, strategies and risk controls." : "Every page and control. Simple keeps only the essentials."}
      </p>
    </div>
  );
}

function Brand() {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-[13px] font-bold text-on-primary" aria-hidden>
        P
      </span>
      <span className="truncate text-[17px] font-bold tracking-tight text-ink">Pythia</span>
    </span>
  );
}

function Chrome() {
  const [page, setPage] = useState<PageId>("home");
  const narrow = useNarrow();
  const [sidebar, setSidebar] = useState(() => !(window.matchMedia?.(NARROW).matches ?? false));
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
  const current = isVisible(page, mode) ? (resolvePage(page) as keyof typeof PAGES) : "home";

  function go(id: PageId) {
    setPage(id);
    if (narrow) setSidebar(false);
    mainRef.current?.scrollTo({ top: 0 });
  }

  // A page asking for another (Home's insights open Research).
  const goRef = useRef(go);
  goRef.current = go;
  useEffect(() => onOpenPage((id) => goRef.current(id)), []);

  const navBody = (
    <div className="flex h-full w-[264px] flex-col md:w-60">
      {narrow && (
        <div className="flex items-center justify-between px-4 pb-1 pt-4">
          <Brand />
          <button
            type="button"
            onClick={() => setSidebar(false)}
            aria-label="Close the menu"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-ink hover:bg-line"
          >
            <X size={17} aria-hidden />
          </button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {sections.map((section, si) => (
          <div key={section} className={si === 0 ? "" : "mt-5"}>
            <div className="mb-1 px-3 text-[12px] font-semibold text-faint">{section}</div>
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
                    className={`flex h-10 w-full items-center gap-3 rounded-control px-3 text-[15px] transition-colors ${
                      active ? "bg-surface-2 font-semibold text-ink" : "text-muted hover:bg-surface-2 hover:text-ink"
                    }`}
                  >
                    <Icon size={18} strokeWidth={active ? 2.2 : 1.8} aria-hidden className="shrink-0" />
                    <span className="truncate">{item.label}</span>
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
    <div className="app-window">
      {/* top bar */}
      <div className="titlebar flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-canvas px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-1.5">
          {!narrow && (
            <button
              type="button"
              onClick={() => setSidebar((s) => !s)}
              aria-label={sidebar ? "Hide the menu" : "Show the menu"}
              aria-expanded={sidebar}
              aria-controls="main-nav"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <PanelLeft size={18} aria-hidden />
            </button>
          )}
          <Brand />
        </div>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <DataHealthBadge />
          <ModePill />
          <StopButton />
          {!narrow && <ThemeButton />}
          {/* Window controls only mean something in the desktop app. */}
          {native && (
            <>
              <button
                type="button"
                onClick={() => void minimizeWindow()}
                aria-label="Minimize"
                title="Minimize"
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-ink"
              >
                <Minus size={16} aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => void hideWindow()}
                aria-label="Close to tray"
                title="Close to tray (keeps running)"
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-ink"
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
                  className="absolute inset-0 z-30 bg-black/40"
                  aria-hidden
                />
                <motion.nav
                  key="drawer"
                  id="main-nav"
                  aria-label="Pages"
                  initial={{ x: "-100%" }}
                  animate={{ x: 0 }}
                  exit={{ x: "-100%" }}
                  transition={{ type: "tween", duration: 0.2, ease: "easeOut" }}
                  className="absolute inset-y-0 left-0 z-40 max-w-[85vw] bg-surface shadow-pop"
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
                animate={{ width: 240, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.18 }}
                className="shrink-0 overflow-hidden border-r border-line bg-canvas"
              >
                {navBody}
              </motion.nav>
            )}
          </AnimatePresence>
        )}

        {/* page host: all pages mounted, inactive hidden, for instant switching */}
        <main ref={mainRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-canvas">
          {(Object.keys(PAGES) as (keyof typeof PAGES)[]).map((id) => {
            const Page = PAGES[id];
            return (
              <div key={id} style={{ display: current === id ? "block" : "none" }} className="px-4 pb-12 pt-6 sm:px-8 sm:pt-8">
                <ErrorBoundary>
                  <Page />
                </ErrorBoundary>
              </div>
            );
          })}
        </main>
      </div>

      {/* a phone gets bottom tabs for the everyday pages; the rest sit behind More */}
      {narrow && (
        <TabBar<PageId | "more">
          label="Main pages"
          items={[...tabsFor(mode), { id: "more", label: "More", icon: Menu }]}
          active={sidebar ? "more" : activeTab(current)}
          onSelect={(id) => (id === "more" ? setSidebar((s) => !s) : go(id))}
        />
      )}
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
