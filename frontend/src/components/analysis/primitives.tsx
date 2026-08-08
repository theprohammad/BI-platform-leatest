/**
 * Analysis primitives — retuned to the premium design system.
 * These render across all legacy feature screens (market, competitors, leads,
 * audit, pricing, opportunity, outreach), so styling them here elevates every
 * screen at once. No default shadcn / admin-dashboard styling.
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Panel, Reveal } from "@/components/premium/primitives";

export function SectionHeader({
  title,
  description,
  icon,
  action,
  className,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mb-7 flex flex-col gap-2 md:flex-row md:items-end md:justify-between",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        {icon ? (
          <div className="mt-0.5 grid h-10 w-10 place-items-center rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] text-fuchsia-300">
            {icon}
          </div>
        ) : null}
        <div>
          <h2 className="text-[22px] font-semibold leading-tight tracking-[-0.01em]">{title}</h2>
          {description ? (
            <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <Panel interactive className="group relative overflow-hidden p-5">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </p>
        {icon ? (
          <div className="text-muted-foreground transition-colors group-hover:text-fuchsia-300">
            {icon}
          </div>
        ) : null}
      </div>
      <div className="tabular mt-3 text-[28px] font-semibold leading-none tracking-tight">
        {value}
      </div>
      {hint ? <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p> : null}
    </Panel>
  );
}

export function InsightCard({
  title,
  children,
  footer,
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={cn("p-5", className)}>
      {title ? <h3 className="mb-3 text-[13px] font-semibold tracking-tight">{title}</h3> : null}
      <div className="text-[13.5px] leading-relaxed">{children}</div>
      {footer ? <div className="mt-4">{footer}</div> : null}
    </Panel>
  );
}

export function BadgeList({
  items,
  variant = "default",
}: {
  items?: string[];
  variant?: "default" | "success" | "warning" | "danger" | "info";
}) {
  if (!items || items.length === 0) return null;
  const styles: Record<string, string> = {
    default: "bg-[var(--surface-3)] text-foreground/90 border-[var(--hairline)]",
    success: "bg-emerald-500/12 text-emerald-300 border-emerald-500/25",
    warning: "bg-amber-500/12 text-amber-300 border-amber-500/25",
    danger: "bg-rose-500/12 text-rose-300 border-rose-500/25",
    info: "bg-sky-500/12 text-sky-300 border-sky-500/25",
  };
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((it, i) => (
        <span
          key={`${i}-${it}`}
          className={cn(
            "inline-flex items-center rounded-lg border px-2.5 py-1 text-[12px] font-medium",
            styles[variant],
          )}
        >
          {it}
        </span>
      ))}
    </div>
  );
}

export function BulletList({ items }: { items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="space-y-2.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2.5 text-[13.5px]">
          <span className="mt-[7px] inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-br from-violet-400 to-fuchsia-500" />
          <span className="leading-relaxed text-foreground/90">{it}</span>
        </li>
      ))}
    </ul>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-[var(--hairline)] bg-[var(--surface)]/40 px-6 py-12 text-center">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {description ? (
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      ) : null}
    </div>
  );
}

export function PriorityBadge({ priority }: { priority?: string }) {
  if (!priority) return null;
  const p = priority.toLowerCase();
  const cls =
    p === "high"
      ? "bg-rose-500/12 text-rose-300 border-rose-500/25"
      : p === "medium"
        ? "bg-amber-500/12 text-amber-300 border-amber-500/25"
        : "bg-emerald-500/12 text-emerald-300 border-emerald-500/25";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
        cls,
      )}
    >
      {priority}
    </span>
  );
}

// Re-export for sections that want staggered entrance.
export { Reveal };
