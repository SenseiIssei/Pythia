import {
  Home,
  LayoutDashboard,
  LineChart,
  Wallet,
  Coins,
  Cpu,
  ShieldAlert,
  ScrollText,
  Settings,
  Info,
  FlaskConical,
  BarChart3,
  Sparkles,
  Blocks,
  Grid3x3,
  BrainCircuit,
  Target,
  Radio,
  Gauge,
  Microscope,
  Plane,
  Crosshair,
  History,
  Bell,
  BookOpen,
  Layers,
  QrCode,
  type LucideIcon,
} from "lucide-react";
import type { UiMode } from "./uiMode";

export type PageId =
  | "home"
  | "practice"
  | "autopilot"
  | "activity"
  | "notifications"
  | "dashboard"
  | "markets"
  | "positions"
  | "wallets"
  | "strategies"
  | "composer"
  | "backtest"
  | "optimizer"
  | "analytics"
  | "correlation"
  | "cs2"
  | "signals"
  | "models"
  | "lab"
  | "research"
  | "predictions"
  | "cards"
  | "live"
  | "pumpfun"
  | "risk"
  | "journal"
  | "settings"
  | "about";

export interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
  section: string;
  /**
   * Hidden in simple mode. Everything here needs trading vocabulary to read, or
   * exposes a knob a beginner has no basis for turning.
   */
  advanced?: boolean;
}

export const NAV: NavItem[] = [
  // ── always visible ──
  { id: "home", label: "Home", icon: Home, section: "Overview" },
  { id: "autopilot", label: "Autopilot", icon: Plane, section: "Overview" },
  { id: "activity", label: "Activity", icon: History, section: "Overview" },
  { id: "notifications", label: "Notifications", icon: Bell, section: "Overview" },
  { id: "predictions", label: "Predictions", icon: Target, section: "Overview" },
  { id: "wallets", label: "Money", icon: Coins, section: "Overview" },
  // Pokemon cards: prices and forecasts, paper only. Plain enough for simple mode.
  { id: "cards", label: "Cards", icon: Layers, section: "Overview" },

  // ── advanced only ──
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, section: "Overview", advanced: true },
  { id: "markets", label: "Markets", icon: LineChart, section: "Trading", advanced: true },
  { id: "positions", label: "Positions", icon: Wallet, section: "Trading", advanced: true },
  { id: "strategies", label: "Strategies", icon: Cpu, section: "Trading", advanced: true },
  { id: "research", label: "Research", icon: BookOpen, section: "Research", advanced: true },
  { id: "composer", label: "Composer", icon: Blocks, section: "Research", advanced: true },
  { id: "backtest", label: "Backtest", icon: FlaskConical, section: "Research", advanced: true },
  { id: "optimizer", label: "Optimizer", icon: Sparkles, section: "Research", advanced: true },
  { id: "analytics", label: "Analytics", icon: BarChart3, section: "Research", advanced: true },
  { id: "correlation", label: "Correlation", icon: Grid3x3, section: "Research", advanced: true },
  { id: "cs2", label: "CS2 Skins", icon: Crosshair, section: "Research", advanced: true },
  { id: "signals", label: "AI Signals", icon: BrainCircuit, section: "AI", advanced: true },
  { id: "models", label: "Models", icon: Gauge, section: "AI", advanced: true },
  { id: "lab", label: "Lab", icon: Microscope, section: "AI", advanced: true },
  { id: "live", label: "Live", icon: Radio, section: "Control", advanced: true },
  // The owner's real-money pump.fun test: funding address, balance, limits, kill switch (docs/PUMPFUN-LIVE.md).
  { id: "pumpfun", label: "pump.fun wallet", icon: QrCode, section: "Control", advanced: true },
  { id: "risk", label: "Risk", icon: ShieldAlert, section: "Control", advanced: true },
  { id: "journal", label: "Journal", icon: ScrollText, section: "Control", advanced: true },

  // ── always visible ──
  { id: "settings", label: "Settings", icon: Settings, section: "Config" },
  { id: "about", label: "About", icon: Info, section: "Config" },
];

/**
 * Pages that moved. Practice now lives on the Autopilot page; the old id
 * still leads there, so a saved link or an old button keeps working.
 */
export const REDIRECTS: Partial<Record<PageId, PageId>> = {
  practice: "autopilot",
};

/** Where a page id leads now. */
export function resolvePage(id: PageId): PageId {
  return REDIRECTS[id] ?? id;
}

/** The nav for one mode. Simple keeps the beginner entries; advanced keeps everything. */
export function navFor(mode: UiMode): NavItem[] {
  return mode === "advanced" ? NAV : NAV.filter((n) => !n.advanced);
}

export function isVisible(id: PageId, mode: UiMode): boolean {
  const to = resolvePage(id);
  return navFor(mode).some((n) => n.id === to);
}

/** The phone's bottom tabs, in order. Everything else sits behind "More". */
export const TAB_IDS: PageId[] = ["home", "autopilot", "activity", "notifications"];

/** Short tab labels: a phone has about 70 px per tab. */
const TAB_LABEL: Partial<Record<PageId, string>> = { notifications: "Alerts" };

export function tabsFor(mode: UiMode): NavItem[] {
  const nav = navFor(mode);
  return TAB_IDS.flatMap((id) => {
    const n = nav.find((x) => x.id === id);
    return n ? [{ ...n, label: TAB_LABEL[id] ?? n.label }] : [];
  });
}

/**
 * Which bottom tab is lit for a page: its own tab, or "more" for a page that
 * only the menu reaches.
 */
export function activeTab(page: PageId): PageId | "more" {
  const to = resolvePage(page);
  return TAB_IDS.includes(to) ? to : "more";
}
