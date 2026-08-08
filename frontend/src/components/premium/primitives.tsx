/**
 * Premium primitives — the shared vocabulary of the intelligence workspace.
 * Motion, elevation, skeletons, confidence visualization. Framework-free
 * (CSS + a tiny bit of state) so they stay fast and dependency-light.
 */
import { type ReactNode, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/* ---- Motion: reveal children on mount / when they enter the viewport ---- */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const prefersReduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(prefersReduced);
  useEffect(() => {
    if (prefersReduced) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [prefersReduced]);
  return (
    <div
      ref={ref}
      className={cn(
        "transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
        shown ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0",
        className,
      )}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/* ---- Panel: the canonical elevated surface ------------------------------ */
export function Panel({
  children,
  className,
  interactive = false,
  as: Tag = "div",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
  as?: React.ElementType;
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={cn(
        "rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/80 backdrop-blur-sm",
        interactive &&
          "transition-all duration-200 hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)] hover:bg-[var(--surface-2)]/80 hover:shadow-[0_8px_30px_-12px_rgba(0,0,0,0.6)]",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/* ---- Skeleton ----------------------------------------------------------- */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} />;
}

export function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/60 p-5">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-xl" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-3 w-1/3" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <div className="mt-4 space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    </div>
  );
}

/* ---- Confidence meter: the signature trust visualization ---------------- */
export function ConfidenceMeter({
  value,
  size = "md",
  showLabel = true,
}: {
  value: number;
  size?: "sm" | "md";
  showLabel?: boolean;
}) {
  const pct = Math.round((value ?? 0) * 100);
  const hue = pct >= 70 ? 150 : pct >= 45 ? 60 : 22; // green / amber / red
  const color = `oklch(0.72 0.16 ${hue})`;
  const track = 4;
  const dim = size === "sm" ? 28 : 36;
  const r = (dim - track) / 2;
  const circ = 2 * Math.PI * r;
  return (
    <div className="inline-flex items-center gap-2" title={`${pct}% confidence`}>
      <svg width={dim} height={dim} className="-rotate-90">
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={r}
          fill="none"
          stroke="color-mix(in oklch, currentColor 12%, transparent)"
          strokeWidth={track}
        />
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={track}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct / 100)}
          style={{
            transition: "stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)",
          }}
        />
      </svg>
      {showLabel && (
        <span className="tabular text-sm font-semibold" style={{ color }}>
          {pct}%
        </span>
      )}
    </div>
  );
}

/* ---- Sparkline: inline trend, no chart lib ------------------------------ */
export function Sparkline({
  data,
  width = 96,
  height = 28,
  className,
}: {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((d - min) / span) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const rising = data[data.length - 1] >= data[0];
  const stroke = rising ? "oklch(0.72 0.15 150)" : "oklch(0.65 0.19 22)";
  return (
    <svg width={width} height={height} className={className} fill="none">
      <polyline
        points={pts.join(" ")}
        stroke={stroke}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={pts[pts.length - 1].split(",")[0]}
        cy={pts[pts.length - 1].split(",")[1]}
        r={2.5}
        fill={stroke}
      />
    </svg>
  );
}

/* ---- Empty state: never a dead end -------------------------------------- */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--hairline)] px-6 py-16 text-center">
      <div className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--surface-2)] text-muted-foreground">
        <Icon className="h-6 w-6" />
      </div>
      <h3 className="mt-4 text-[15px] font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ---- Keyboard hint ------------------------------------------------------ */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-[var(--hairline)] bg-[var(--surface-2)] px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
      {children}
    </kbd>
  );
}
