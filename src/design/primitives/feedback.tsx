import type { ReactNode } from "react";
import { CheckCircle2, Info, Loader2, ShieldAlert, TriangleAlert, type LucideIcon } from "lucide-react";

/** What a section says when there is nothing to show yet, and what to do about it. */
export function Empty({ icon: Icon, title, children, action, compact }: { icon?: LucideIcon; title: ReactNode; children?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={`flex flex-col items-center px-4 text-center ${compact ? "py-5" : "py-10"}`}>
      {Icon && (
        <span className={`mb-3 flex items-center justify-center rounded-full bg-surface-2 text-ink ${compact ? "h-10 w-10" : "h-14 w-14"}`} aria-hidden>
          <Icon size={compact ? 18 : 24} />
        </span>
      )}
      <h3 className={`${compact ? "text-[15px]" : "text-lg"} font-semibold text-ink`}>{title}</h3>
      {children && <div className="mt-1 max-w-sm text-sm leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** A grey placeholder in the shape of what is loading. */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`pt-skeleton ${className}`} aria-hidden />;
}

/** A quiet spinner with words. */
export function Spinner({ children = "Loading" }: { children?: ReactNode }) {
  return (
    <div role="status" className="flex items-center gap-2 py-3 text-sm text-muted">
      <Loader2 size={15} aria-hidden className="animate-spin" />
      {children}
    </div>
  );
}

export type NoticeTone = "info" | "success" | "warning" | "danger";

/**
 * A soft tinted box. `info` explains, `success` reassures, `warning` asks for
 * care, `danger` is about real money or something broken.
 */
export function Notice({
  tone = "info",
  title,
  icon,
  children,
  action,
  className = "",
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  icon?: LucideIcon;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const look = {
    info: { box: "bg-surface-2", text: "text-ink", icon: "text-accent", Icon: Info },
    success: { box: "bg-up/[0.08]", text: "text-up", icon: "text-up", Icon: CheckCircle2 },
    warning: { box: "bg-warn/10", text: "text-warn", icon: "text-warn", Icon: TriangleAlert },
    danger: { box: "bg-down/[0.08]", text: "text-down", icon: "text-down", Icon: ShieldAlert },
  }[tone];
  const Icon = icon ?? look.Icon;
  return (
    <div role={tone === "danger" || tone === "warning" ? "alert" : undefined} className={`flex flex-wrap items-start gap-3 rounded-2xl px-4 py-3.5 ${look.box} ${className}`}>
      <Icon size={18} aria-hidden className={`mt-0.5 shrink-0 ${look.icon}`} />
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-muted">
        {title && <div className={`font-semibold ${look.text}`}>{title}</div>}
        {children}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
    </div>
  );
}
