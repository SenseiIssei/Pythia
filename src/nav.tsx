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
  type LucideIcon,
} from "lucide-react";
import type { UiMode } from "./uiMode";

export type PageId =
  | "home"
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
  | "signals"
  | "models"
  | "lab"
  | "predictions"
  | "live"
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
  { id: "predictions", label: "Predictions", icon: Target, section: "Overview" },
  { id: "wallets", label: "Money", icon: Coins, section: "Overview" },

  // ── advanced only ──
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, section: "Overview", advanced: true },
  { id: "markets", label: "Markets", icon: LineChart, section: "Trading", advanced: true },
  { id: "positions", label: "Positions", icon: Wallet, section: "Trading", advanced: true },
  { id: "strategies", label: "Strategies", icon: Cpu, section: "Trading", advanced: true },
  { id: "composer", label: "Composer", icon: Blocks, section: "Research", advanced: true },
  { id: "backtest", label: "Backtest", icon: FlaskConical, section: "Research", advanced: true },
  { id: "optimizer", label: "Optimizer", icon: Sparkles, section: "Research", advanced: true },
  { id: "analytics", label: "Analytics", icon: BarChart3, section: "Research", advanced: true },
  { id: "correlation", label: "Correlation", icon: Grid3x3, section: "Research", advanced: true },
  { id: "signals", label: "AI Signals", icon: BrainCircuit, section: "AI", advanced: true },
  { id: "models", label: "Models", icon: Gauge, section: "AI", advanced: true },
  { id: "lab", label: "Lab", icon: Microscope, section: "AI", advanced: true },
  { id: "live", label: "Live", icon: Radio, section: "Control", advanced: true },
  { id: "risk", label: "Risk", icon: ShieldAlert, section: "Control", advanced: true },
  { id: "journal", label: "Journal", icon: ScrollText, section: "Control", advanced: true },

  // ── always visible ──
  { id: "settings", label: "Settings", icon: Settings, section: "Config" },
  { id: "about", label: "About", icon: Info, section: "Config" },
];

/** The nav for one mode. Simple keeps five entries; advanced keeps everything. */
export function navFor(mode: UiMode): NavItem[] {
  return mode === "advanced" ? NAV : NAV.filter((n) => !n.advanced);
}

export function isVisible(id: PageId, mode: UiMode): boolean {
  return navFor(mode).some((n) => n.id === id);
}
