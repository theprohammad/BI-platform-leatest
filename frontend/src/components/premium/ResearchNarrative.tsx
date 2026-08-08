/**
 * Cinematic live research narrative — the "watch the AI think" moment.
 * Renders the SSE event stream as an elegant, animated activity timeline
 * with stage grouping, live counters, and a shimmer on the active step.
 */
import { useEffect, useMemo, useRef } from "react";
import {
  Brain,
  CheckCircle2,
  Database,
  FileSearch,
  GitBranch,
  Lightbulb,
  Loader2,
  Scale,
  Search,
  Sparkles,
  Telescope,
} from "lucide-react";
import type { RunEvent } from "@/services/intelligence";
import { cn } from "@/lib/utils";

const STAGE_META: Record<string, { icon: React.ElementType; label: string }> = {
  understand: { icon: Telescope, label: "Building profile" },
  hypothesize: { icon: Brain, label: "Forming hypotheses" },
  investigate: { icon: Search, label: "Investigating" },
  replan: { icon: GitBranch, label: "Re-planning" },
  verify: { icon: CheckCircle2, label: "Verifying citations" },
  reconcile: { icon: Database, label: "Organizing intelligence" },
  synthesize: { icon: Sparkles, label: "Synthesizing findings" },
  debate: { icon: Scale, label: "Cross-checking sources" },
  adjudicate: { icon: Scale, label: "Resolving conflicts" },
  recommend: { icon: Lightbulb, label: "Recommendations" },
  refresh: { icon: FileSearch, label: "Refreshing" },
};

function stageOf(e: RunEvent): string | null {
  if (e.type === "research.stage") return (e.payload.stage as string) ?? null;
  return null;
}

export function ResearchNarrative({ events }: { events: RunEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const { steps, counts } = useMemo(() => {
    const steps: { stage: string; detail: string; done: boolean }[] = [];
    const counts = { evidence: 0, claims: 0, edges: 0, insights: 0 };
    for (const e of events) {
      const stage = stageOf(e);
      if (stage) {
        const detail =
          (e.payload.detail as string) ||
          (e.payload.question as string) ||
          (e.payload.topic ? `Topic: ${e.payload.topic}` : "") ||
          "";
        steps.push({ stage, detail, done: false });
      }
      if (e.type === "research.extracted") {
        counts.claims += (e.payload.claims as number) ?? 0;
        counts.edges += (e.payload.edges as number) ?? 0;
      }
      if (e.type === "research.done") {
        counts.claims = (e.payload.claims as number) ?? counts.claims;
      }
    }
    // mark all but the last as done
    steps.forEach((s, i) => (s.done = i < steps.length - 1));
    return { steps, counts };
  }, [events]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [steps.length]);

  return (
    <div className="mx-auto max-w-3xl">
      {/* Live status hero */}
      <div className="relative overflow-hidden rounded-3xl border border-[var(--hairline)] bg-[var(--surface)]/70 p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-fuchsia-500/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="relative flex items-center gap-4">
          <div className="relative grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-fuchsia-500/25">
            <Brain className="h-7 w-7 text-white" />
            <span className="absolute inset-0 rounded-2xl ring-2 ring-fuchsia-400/40 [animation:ping_2s_cubic-bezier(0,0,0.2,1)_infinite]" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[15px] font-semibold">
              Research in progress
              <Loader2 className="h-3.5 w-3.5 animate-spin text-fuchsia-300" />
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Multi-agent analysis across market, competitors, and evidence graph.
            </p>
          </div>
        </div>

        <div className="relative mt-6 grid grid-cols-3 gap-3">
          <LiveCounter label="Findings" value={counts.claims} />
          <LiveCounter label="Relationships" value={counts.edges} />
          <LiveCounter label="Steps" value={steps.length} />
        </div>
      </div>

      {/* Activity timeline */}
      <div ref={scrollRef} className="mt-5 max-h-[420px] space-y-1 overflow-y-auto pr-1">
        {steps.map((step, i) => {
          const meta = STAGE_META[step.stage] ?? { icon: Sparkles, label: step.stage };
          const Icon = meta.icon;
          const active = i === steps.length - 1;
          return (
            <div
              key={i}
              className={cn(
                "flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors animate-[rise_0.4s_cubic-bezier(0.16,1,0.3,1)]",
                active && "bg-[var(--surface-2)]/50",
              )}
            >
              <div
                className={cn(
                  "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border transition-colors",
                  active
                    ? "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300"
                    : "border-[var(--hairline)] bg-[var(--surface-2)] text-emerald-400",
                )}
              >
                {active ? (
                  <Icon className="h-3.5 w-3.5" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
              </div>
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{meta.label}</span>
                  {active && (
                    <span className="text-[11px] text-fuchsia-300/80 [animation:fade-in_0.6s]">
                      working…
                    </span>
                  )}
                </div>
                {step.detail && (
                  <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{step.detail}</p>
                )}
              </div>
            </div>
          );
        })}
        {steps.length === 0 && (
          <div className="flex items-center gap-3 rounded-xl px-3 py-2.5">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            <span className="text-[13px] text-muted-foreground">Initializing agents…</span>
          </div>
        )}
      </div>
    </div>
  );
}

function LiveCounter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-4 py-3">
      <div className="tabular text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}
