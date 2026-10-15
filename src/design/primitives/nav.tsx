import type { LucideIcon } from "lucide-react";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon: LucideIcon;
  /** A small count on the icon, like unread notifications. */
  badge?: number;
}

/** The phone's bottom tab bar: icon over a short label, the active one in ink. */
export function TabBar<T extends string>({ items, active, onSelect, label = "Tabs" }: { items: TabItem<T>[]; active: T; onSelect: (id: T) => void; label?: string }) {
  return (
    <nav aria-label={label} className="pt-safe-bottom shrink-0 border-t border-line bg-surface/95 backdrop-blur">
      <ul className="grid" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
        {items.map((t) => {
          const on = t.id === active;
          const Icon = t.icon;
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => onSelect(t.id)}
                aria-current={on ? "page" : undefined}
                className={`flex min-h-[56px] w-full flex-col items-center justify-center gap-1 px-1 text-[11px] font-semibold transition-colors ${on ? "text-ink" : "text-faint hover:text-muted"}`}
              >
                <span className="relative">
                  <Icon size={22} strokeWidth={on ? 2.3 : 1.8} aria-hidden />
                  {!!t.badge && (
                    <span className="absolute -right-2 -top-1 min-w-[16px] rounded-full bg-down px-1 text-center text-[10px] font-bold leading-4 text-on-down">
                      {t.badge > 9 ? "9+" : t.badge}
                      <span className="sr-only"> new</span>
                    </span>
                  )}
                </span>
                <span className="max-w-full truncate">{t.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
