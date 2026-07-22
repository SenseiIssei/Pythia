import {
  LayoutDashboard,
  LineChart,
  Wallet,
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
  type LucideIcon,
} from "lucide-react";

export type PageId =
  | "dashboard"
  | "markets"
  | "positions"
  | "strategies"
  | "composer"
  | "backtest"
  | "optimizer"
  | "analytics"
  | "correlation"
  | "risk"
  | "journal"
  | "settings"
  | "about";

export interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
  section: string;
}

export const NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, section: "Overview" },
  { id: "markets", label: "Markets", icon: LineChart, section: "Trading" },
  { id: "positions", label: "Positions", icon: Wallet, section: "Trading" },
  { id: "strategies", label: "Strategies", icon: Cpu, section: "Trading" },
  { id: "composer", label: "Composer", icon: Blocks, section: "Research" },
  { id: "backtest", label: "Backtest", icon: FlaskConical, section: "Research" },
  { id: "optimizer", label: "Optimizer", icon: Sparkles, section: "Research" },
  { id: "analytics", label: "Analytics", icon: BarChart3, section: "Research" },
  { id: "correlation", label: "Correlation", icon: Grid3x3, section: "Research" },
  { id: "risk", label: "Risk", icon: ShieldAlert, section: "Control" },
  { id: "journal", label: "Journal", icon: ScrollText, section: "Control" },
  { id: "settings", label: "Settings", icon: Settings, section: "Config" },
  { id: "about", label: "About", icon: Info, section: "Config" },
];
