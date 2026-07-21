import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

// ── shared neon UI kit (mirrors Odysync's components/ui.tsx) ────────────────

type Tone = "cyan" | "purple" | "green" | "red" | "neutral";

const toneMap: Record<Tone, string> = {
  cyan: "bg-accent/10 border-accent/30 text-accent hover:bg-accent/20 glow-cyan",
  purple: "bg-purple-neon/10 border-purple-neon/30 text-purple-neon hover:bg-purple-neon/20 glow-purple",
  green: "bg-success/10 border-success/30 text-success hover:bg-success/20 glow-green",
  red: "bg-danger/10 border-danger/30 text-danger hover:bg-danger/20 glow-red",
  neutral: "bg-cyber-surface-2 border-cyber-border-bright text-cyber-text hover:bg-cyber-border-bright",
};

export function Button({
  children,
  onClick,
  tone = "cyan",
  disabled,
  icon: Icon,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: Tone;
  disabled?: boolean;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <motion.button
      whileHover={disabled ? undefined : { scale: 1.02 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${toneMap[tone]} ${className}`}
    >
      {Icon && <Icon size={15} />}
      {children}
    </motion.button>
  );
}

export function Card({
  title,
  children,
  className = "",
  right,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
  right?: ReactNode;
}) {
  return (
    <div className={`rounded-lg border border-cyber-border bg-cyber-surface p-4 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <div className="text-sm font-bold text-accent">{title}</div>}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "cyan",
  delay = 0,
  sub,
}: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  delay?: number;
  sub?: ReactNode;
}) {
  const color =
    tone === "green" ? "text-success" : tone === "red" ? "text-danger" : tone === "purple" ? "text-purple-neon" : "text-accent";
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="rounded-xl border border-cyber-border bg-cyber-surface p-4"
    >
      <div className="flex items-center gap-2 text-cyber-text-dim">
        <Icon size={14} className={color} />
        <span className="text-xs uppercase tracking-wide">{label}</span>
      </div>
      <div className={`mt-2 text-2xl font-bold ${color}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-cyber-text-faint">{sub}</div>}
    </motion.div>
  );
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-2xl font-bold text-glow-cyan">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-cyber-text-dim">{subtitle}</p>}
    </div>
  );
}

export function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={`relative h-6 w-11 rounded-full border transition-colors ${
        on ? "border-accent/50 bg-accent/30" : "border-cyber-border-bright bg-cyber-surface-2"
      }`}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
        className={`absolute top-0.5 h-4 w-4 rounded-full ${on ? "right-0.5 bg-accent" : "left-0.5 bg-cyber-text-faint"}`}
      />
    </button>
  );
}

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  const map: Record<Tone, string> = {
    cyan: "border-accent/40 text-accent",
    purple: "border-purple-neon/40 text-purple-neon",
    green: "border-success/40 text-success",
    red: "border-danger/40 text-danger",
    neutral: "border-cyber-border-bright text-cyber-text-dim",
  };
  return (
    <span className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${map[tone]}`}>
      {children}
    </span>
  );
}

export function Meter({ pct, tone = "cyan" }: { pct: number; tone?: Tone }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const bar =
    tone === "red" ? "bg-danger" : tone === "green" ? "bg-success" : tone === "purple" ? "bg-purple-neon" : "bg-accent";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-cyber-surface-2">
      <motion.div
        className={`h-full ${bar}`}
        initial={{ width: 0 }}
        animate={{ width: `${clamped}%` }}
        transition={{ duration: 0.4 }}
      />
    </div>
  );
}

// tiny inline sparkline / equity curve
export function Sparkline({
  data,
  tone = "cyan",
  height = 48,
}: {
  data: number[];
  tone?: Tone;
  height?: number;
}) {
  if (data.length < 2) {
    return <div style={{ height }} className="flex items-center text-xs text-cyber-text-faint">gathering data…</div>;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 100;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const stroke =
    tone === "green" ? "#22c55e" : tone === "red" ? "#ef4444" : tone === "purple" ? "#a855f7" : "#00f0ff";
  const last = data[data.length - 1];
  const first = data[0];
  const up = last >= first;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }}>
      <polyline
        points={pts}
        fill="none"
        stroke={up ? stroke : "#ef4444"}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function fmtUsd(n: number, dp = 2): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
}

export function fmtPct(n: number, dp = 1): string {
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(dp)}%`;
}
