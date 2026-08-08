/**
 * Executive Dashboard — the morning briefing.
 * Aggregates real intelligence across every twin: KPI ribbon, priority feed
 * (severity + confidence ranked, evidence-backed), twin portfolio, and today's
 * discoveries. All data from /v2/briefing — nothing fabricated. Progressive
 * disclosure: every item drills into the Workspace.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Brain,
  Command,
  Database,
  Lightbulb,
  Radar,
  Target,
  Scale,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import {
  ConfidenceMeter,
  EmptyState,
  Kbd,
  Panel,
  Reveal,
  Skeleton,
} from "@/components/premium/primitives";
import { cn } from "@/lib/utils";
import {
  fetchBriefing,
  fetchCompetitorTimeline,
  fetchDashboard,
  fetchMonitoringStatus,
  fetchPipeline,
  type Discovery,
  type ExecutiveBriefing,
  type PriorityItem,
} from "@/services/intelligence";
import { useActiveOrg } from "@/hooks/use-active-org";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Briefing — Sentient Intelligence OS" }] }),
  component: HomePage,
});

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function HomePage() {
  const navigate = useNavigate();
  const {
    data: brief,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["briefing"],
    queryFn: fetchBriefing,
  });

  return (
    <AppShell title="Briefing">
      {isError ? (
        <Panel className="p-16 text-center text-sm text-rose-400">
          Couldn't load your briefing. Please retry in a moment.
        </Panel>
      ) : isLoading || !brief ? (
        <BriefingSkeleton />
      ) : !brief.has_data ? (
        <FirstRun onStart={() => navigate({ to: "/intelligence" })} />
      ) : (
        <Briefing brief={brief} navigate={navigate} />
      )}
    </AppShell>
  );
}

function Briefing({
  brief,
  navigate,
}: {
  brief: ExecutiveBriefing;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const t = brief.totals;
  const attention = brief.priority_feed.filter(
    (p) => p.severity === "high" || p.severity === "urgent",
  ).length;

  return (
    <div className="space-y-8">
      {/* Editorial hero — the brief, in prose */}
      <Reveal>
        <div className="relative overflow-hidden rounded-3xl border border-[var(--hairline)] bg-[var(--surface)]/60 p-8 sm:p-10">
          <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-fuchsia-500/10 blur-3xl" />
          <div className="relative">
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Intelligence synced {relTime(brief.generated_at)}
            </div>
            <h1 className="mt-3 text-[30px] font-semibold leading-[1.12] tracking-[-0.02em] sm:text-[38px]">
              {greeting()}.
            </h1>
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
              Across <span className="font-medium text-foreground">{brief.twins.length}</span>{" "}
              {brief.twins.length === 1 ? "organization" : "organizations"}, your intelligence
              system is tracking <span className="font-medium text-foreground">{t.validated}</span>{" "}
              verified finding
              {t.validated === 1 ? "" : "s"} and{" "}
              <span className="font-medium text-foreground">{t.recommendations}</span>{" "}
              recommendation{t.recommendations === 1 ? "" : "s"}.
              {attention > 0 ? (
                <>
                  {" "}
                  <span className="font-medium text-amber-300">{attention}</span>{" "}
                  {attention === 1 ? "item needs" : "items need"} your attention.
                </>
              ) : (
                <> Nothing urgent right now.</>
              )}
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                onClick={() => navigate({ to: "/intelligence" })}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-5 py-2.5 text-[14px] font-medium text-white shadow-lg shadow-fuchsia-500/25 transition-transform hover:scale-[1.02]"
              >
                <Sparkles className="h-4 w-4" /> New Analysis
              </button>
              <button
                onClick={() => navigate({ to: "/workspace" as string })}
                className="inline-flex items-center gap-2 rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/60 px-5 py-2.5 text-[14px] font-medium transition-colors hover:bg-[var(--surface-3)]"
              >
                <Brain className="h-4 w-4" /> Open Workspace
              </button>
              <button
                onClick={() =>
                  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
                }
                className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
              >
                <Command className="h-3.5 w-3.5" /> Search <Kbd>⌘K</Kbd>
              </button>
            </div>
          </div>
        </div>
      </Reveal>

      <ExecutiveSnapshot />

      {/* KPI ribbon — real counts, editorial not card-soup */}
      <Reveal delay={80}>
        <Panel className="grid grid-cols-2 divide-x divide-[var(--hairline)] overflow-hidden sm:grid-cols-3 lg:grid-cols-6">
          <Kpi icon={ShieldCheck} label="Verified findings" value={t.validated} tone="150" />
          <Kpi icon={Lightbulb} label="Recommendations" value={t.recommendations} tone="60" />
          <Kpi icon={Scale} label="Conflicting intelligence" value={t.disputes_open} tone="330" />
          <Kpi icon={Radar} label="Signals" value={t.signals} tone="200" />
          <Kpi icon={Database} label="Evidence links" value={t.evidence} tone="285" />
          <Kpi icon={Activity} label="Research runs" value={t.runs} tone="250" />
        </Panel>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Priority feed — the hero content */}
        <Reveal delay={120}>
          <section>
            <SectionTitle
              icon={AlertTriangle}
              title="Priority feed"
              hint="Ranked by severity, then confidence"
            />
            {brief.priority_feed.length === 0 ? (
              <Panel className="p-8 text-center text-sm text-muted-foreground">
                Nothing needs attention right now. New intelligence will surface here.
              </Panel>
            ) : (
              <div className="space-y-2.5">
                {brief.priority_feed.map((item, i) => (
                  <PriorityCard
                    key={`${item.id}-${i}`}
                    item={item}
                    onOpen={() => navigate({ to: "/workspace" as string })}
                  />
                ))}
              </div>
            )}
          </section>
        </Reveal>

        {/* Right rail: twins + discoveries */}
        <div className="space-y-6">
          <Reveal delay={160}>
            <section>
              <SectionTitle icon={Brain} title="Your organizations" />
              <div className="space-y-2">
                {brief.twins.map((twin) => (
                  <Panel
                    key={twin.id}
                    interactive
                    as="button"
                    onClick={() => navigate({ to: "/workspace" as string })}
                    className="group flex w-full items-center gap-3 p-3.5 text-left"
                  >
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-[11px] font-bold ring-1 ring-[var(--hairline)]">
                      {twin.name
                        .split(/\s+/)
                        .slice(0, 2)
                        .map((w) => w[0])
                        .join("")
                        .toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium">{twin.name}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span className="tabular">{twin.counts.validated} findings</span>
                        <span>·</span>
                        <span className="tabular">{twin.counts.recommendations} actions</span>
                        {twin.counts.disputes_open > 0 && (
                          <>
                            <span>·</span>
                            <span className="tabular text-amber-300">
                              {twin.counts.disputes_open} open
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </Panel>
                ))}
              </div>
            </section>
          </Reveal>

          <Reveal delay={200}>
            <section>
              <SectionTitle icon={TrendingUp} title="Recent discoveries" />
              <Panel className="divide-y divide-[var(--hairline)] p-0">
                {brief.discoveries.slice(0, 8).map((d, i) => (
                  <DiscoveryRow
                    key={`${d.id}-${i}`}
                    d={d}
                    onOpen={() => navigate({ to: "/workspace" as string })}
                  />
                ))}
                {brief.discoveries.length === 0 && (
                  <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                    No discoveries yet.
                  </p>
                )}
              </Panel>
            </section>
          </Reveal>
        </div>
      </div>
    </div>
  );
}

const SEVERITY: Record<string, { dot: string; label: string; text: string }> = {
  urgent: { dot: "bg-rose-500", label: "Urgent", text: "text-rose-300" },
  high: { dot: "bg-amber-400", label: "High", text: "text-amber-300" },
  medium: { dot: "bg-sky-400", label: "Medium", text: "text-sky-300" },
  low: { dot: "bg-muted-foreground", label: "Low", text: "text-muted-foreground" },
};

const KIND_ICON: Record<string, React.ElementType> = {
  dispute: Scale,
  signal: Radar,
  recommendation: Lightbulb,
};

function PriorityCard({ item, onOpen }: { item: PriorityItem; onOpen: () => void }) {
  const sev = SEVERITY[item.severity] ?? SEVERITY.low;
  const Icon = KIND_ICON[item.kind] ?? Sparkles;
  return (
    <Panel
      interactive
      as="button"
      onClick={onOpen}
      className="group flex w-full items-start gap-4 p-4 text-left"
    >
      <div className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] text-fuchsia-300">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide",
              sev.text,
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", sev.dot)} />
            {sev.label}
          </span>
          <span className="text-[11px] text-muted-foreground">· {item.org_name}</span>
          <span className="ml-auto text-[11px] text-muted-foreground">{relTime(item.at)}</span>
        </div>
        <p className="mt-1.5 text-[14px] font-medium leading-snug">{item.title}</p>
        <div className="mt-2.5 flex items-center gap-3">
          <ConfidenceMeter value={item.confidence} size="sm" />
          <span className="text-[11px] text-muted-foreground">
            {item.evidence_count} supporting claim{item.evidence_count === 1 ? "" : "s"}
          </span>
          <span className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-fuchsia-300 opacity-0 transition-opacity group-hover:opacity-100">
            {item.action} <ArrowUpRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Panel>
  );
}

function DiscoveryRow({ d, onOpen }: { d: Discovery; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors first:rounded-t-2xl last:rounded-b-2xl hover:bg-[var(--surface-2)]/40"
    >
      <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-br from-violet-400 to-fuchsia-500" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px]">{d.title}</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {d.org_name} · {d.kind}
        </div>
      </div>
      <span className="tabular shrink-0 text-[11px] text-muted-foreground">{relTime(d.at)}</span>
    </button>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
  tone: string;
}) {
  const color = `oklch(0.72 0.15 ${tone})`;
  return (
    <div className="flex items-center gap-3 p-4">
      <div
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]"
        style={{ color }}
      >
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="tabular text-[22px] font-semibold leading-none tracking-tight">{value}</div>
        <div className="mt-1 truncate text-[11px] text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function SectionTitle({
  icon: Icon,
  title,
  hint,
}: {
  icon: React.ElementType;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-3 flex items-center gap-2 px-1">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {hint && <span className="ml-2 text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  );
}

function FirstRun({ onStart }: { onStart: () => void }) {
  return (
    <EmptyState
      icon={Brain}
      title="Your intelligence system is ready"
      description="Run your first analysis to start building intelligence. Every morning after, this briefing shows what changed, what needs attention, and what to do next."
      action={
        <button
          onClick={onStart}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02]"
        >
          <Sparkles className="h-4 w-4" /> Start first analysis
        </button>
      }
    />
  );
}

function BriefingSkeleton() {
  return (
    <div className="space-y-8">
      <Skeleton className="h-52 w-full rounded-3xl" />
      <Skeleton className="h-20 w-full rounded-2xl" />
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-2.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-2xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
 * Executive snapshot — the three module states an executive needs without
 * opening each module: what to do next, whether we're watching competitors,
 * and where the pipeline stands. Scoped to the active organization and built
 * only from data the platform already holds.
 * ======================================================================== */

function ExecutiveSnapshot() {
  const { activeOrgId, activeOrg } = useActiveOrg();

  const { data: dash } = useQuery({
    queryKey: ["dashboard", activeOrgId, {}],
    queryFn: () => fetchDashboard(activeOrgId!),
    enabled: !!activeOrgId,
  });
  const { data: monitoring } = useQuery({
    queryKey: ["competitor-status", activeOrgId],
    queryFn: () => fetchMonitoringStatus(activeOrgId!),
    enabled: !!activeOrgId,
  });
  const { data: changes } = useQuery({
    queryKey: ["competitor-timeline", activeOrgId],
    queryFn: () => fetchCompetitorTimeline(activeOrgId!),
    enabled: !!activeOrgId,
  });
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline"],
    queryFn: fetchPipeline,
    enabled: !!activeOrgId,
  });

  if (!activeOrgId) return null;

  const recs = dash?.recommendations ?? [];
  const topRecs = [...recs]
    .sort((a, b) => (b.trust?.confidence ?? 0) - (a.trust?.confidence ?? 0))
    .slice(0, 3);

  const watched = monitoring?.watched?.length ?? 0;
  const scans = monitoring?.total_snapshots ?? 0;
  const changeCount = changes?.length ?? 0;
  const latestChange = changes?.[0];

  let monitorState = "Not configured";
  if (watched > 0 && changeCount > 0) monitorState = "Changes detected";
  else if (watched > 0 && scans > watched) monitorState = "Monitoring active";
  else if (watched > 0) monitorState = "Baseline created";

  return (
    <Reveal delay={100}>
      <div className="mb-8 grid gap-3 lg:grid-cols-3">
        {/* Opportunities */}
        <SnapshotCard
          title="Opportunities"
          icon={Lightbulb}
          href="/opportunity-scoring"
          cta="Open Opportunity Engine"
        >
          {topRecs.length === 0 ? (
            <SnapshotEmpty text="No opportunities yet. They appear once an investigation produces recommendations." />
          ) : (
            <ul className="space-y-1.5">
              {topRecs.map((r) => (
                <li key={r.id} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[12.5px]">{r.title}</span>
                  <span className="tabular shrink-0 text-[11px] text-muted-foreground">
                    {Math.round((r.trust?.confidence ?? 0) * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SnapshotCard>

        {/* Competitive watch */}
        <SnapshotCard
          title="Competitive watch"
          icon={Radar}
          href="/monitoring"
          cta="Open Monitoring"
        >
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                monitorState === "Changes detected"
                  ? "bg-amber-500/12 text-amber-300"
                  : monitorState === "Not configured"
                    ? "bg-[var(--surface-3)] text-muted-foreground"
                    : "bg-emerald-500/12 text-emerald-300",
              )}
            >
              {monitorState}
            </span>
            <span className="text-[11px] text-muted-foreground">
              {watched} page{watched === 1 ? "" : "s"} · {scans} scan
              {scans === 1 ? "" : "s"}
            </span>
          </div>
          {latestChange ? (
            <p className="mt-2 line-clamp-2 text-[12px] text-muted-foreground">
              Latest: {latestChange.competitor_name} · {latestChange.summary}
            </p>
          ) : (
            <p className="mt-2 text-[12px] text-muted-foreground">
              {watched > 0
                ? "No material changes since the baseline."
                : "Add a competitor page to start watching for changes."}
            </p>
          )}
        </SnapshotCard>

        {/* Pipeline */}
        <SnapshotCard
          title="Pipeline"
          icon={Target}
          href="/lead-generation"
          cta="Open Lead Intelligence"
        >
          {!pipeline?.has_data ? (
            <SnapshotEmpty text="No leads yet. Analyzed organizations are added automatically." />
          ) : (
            <>
              <div className="flex items-baseline gap-2">
                <span className="tabular text-[20px] font-semibold leading-none">
                  {pipeline.total_leads}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  lead{pipeline.total_leads === 1 ? "" : "s"}
                </span>
              </div>
              <p className="mt-2 text-[12px] text-muted-foreground">
                {(pipeline.by_band?.priority ?? 0) + (pipeline.by_band?.hot ?? 0)} high-priority ·
                avg score {Math.round(pipeline.avg_score ?? 0)}
              </p>
            </>
          )}
        </SnapshotCard>
      </div>
      <div className="sr-only">{activeOrg?.name}</div>
    </Reveal>
  );
}

function SnapshotCard({
  title,
  icon: Icon,
  href,
  cta,
  children,
}: {
  title: string;
  icon: React.ElementType;
  href: string;
  cta: string;
  children: React.ReactNode;
}) {
  return (
    <Panel className="flex flex-col p-4">
      <h3 className="mb-2.5 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" /> {title}
      </h3>
      <div className="min-h-[64px] flex-1">{children}</div>
      <a href={href} className="mt-3 text-[11.5px] font-medium text-fuchsia-300 hover:underline">
        {cta} →
      </a>
    </Panel>
  );
}

function SnapshotEmpty({ text }: { text: string }) {
  return <p className="text-[12px] text-muted-foreground">{text}</p>;
}
