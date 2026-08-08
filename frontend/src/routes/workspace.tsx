/**
 * Intelligence Workspace — the flagship surface.
 * Premium: hero KPI band with sparklines, staggered reveals, skeleton loads,
 * refined tabs, contextual empty/error states, ⌘K-searchable.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Brain,
  ChevronDown,
  ChevronRight,
  Filter,
  Lightbulb,
  Scale,
  Search as SearchIcon,
  ShieldCheck,
  Sparkles,
  Swords,
  TrendingUp,
} from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import {
  ConfidenceMeter,
  EmptyState,
  Panel,
  Reveal,
  Skeleton,
  SkeletonCard,
  Sparkline,
} from "@/components/premium/primitives";
import { StatusBadge } from "@/components/workspace/TrustBadge";
import { FindingDetailDrawer } from "@/components/analysis/FindingDetailDrawer";
import { RecommendationExplorer } from "@/components/workspace/RecommendationExplorer";
import { DebateView } from "@/components/workspace/DebateView";
import { PlaybookSelector } from "@/components/workspace/PlaybookSelector";
import { GlobalSearch } from "@/components/workspace/GlobalSearch";
import { RefreshPanel } from "@/components/workspace/RefreshPanel";
import { cn } from "@/lib/utils";
import {
  fetchAlerts,
  fetchCompetitorTimeline,
  fetchDashboard,
  type CompetitorChange,
  type CriticalAlert,
  type DashboardView,
  type GraphInsight,
} from "@/services/intelligence";
import { useActiveOrg } from "@/hooks/use-active-org";

export const Route = createFileRoute("/workspace")({
  component: WorkspacePage,
});

function WorkspacePage() {
  const {
    activeOrgId,
    setActiveOrgId,
    organizations: orgs,
    activeOrg: activeOrgRecord,
  } = useActiveOrg();
  const activeOrgName = activeOrgRecord?.name ?? "This organization";
  const [statusFilter, setStatusFilter] = useState("all");
  const [playbookFilter, setPlaybookFilter] = useState("all");
  const [sinceFilter, setSinceFilter] = useState("");
  const [claimDialog, setClaimDialog] = useState<string | null>(null);
  const [runPlaybook, setRunPlaybook] = useState<string | null>("full_analysis");

  const activeOrg = activeOrgId;

  const filters = useMemo(
    () => ({
      status: statusFilter === "all" ? undefined : statusFilter,
      playbook: playbookFilter === "all" ? undefined : playbookFilter,
      since: sinceFilter || undefined,
    }),
    [statusFilter, playbookFilter, sinceFilter],
  );

  const {
    data: dash,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["dashboard", activeOrg, filters],
    queryFn: () => fetchDashboard(activeOrg!, filters),
    enabled: !!activeOrg,
  });

  const { data: alertData } = useQuery({
    queryKey: ["alerts", activeOrg],
    queryFn: () => fetchAlerts(activeOrg!),
    enabled: !!activeOrg,
  });
  const { data: competitorChanges } = useQuery({
    queryKey: ["competitor-timeline", activeOrg],
    queryFn: () => fetchCompetitorTimeline(activeOrg!),
    enabled: !!activeOrg,
  });

  const openClaim = (id: string) => setClaimDialog(id);

  return (
    <AppShell title="Workspace">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <PageHeader
          title="Intelligence Workspace"
          description="Your organization's verified intelligence, supporting sources, and prioritized actions — in one place."
        />
        {orgs && orgs.length > 0 && (
          <div className="mb-8 shrink-0">
            <Select value={activeOrg ?? ""} onValueChange={setActiveOrgId}>
              <SelectTrigger className="w-64 rounded-xl border-[var(--hairline)] bg-[var(--surface)]/70">
                <div className="flex items-center gap-2">
                  <div className="grid h-6 w-6 place-items-center rounded-md bg-gradient-to-br from-violet-500/30 to-fuchsia-500/30 text-[10px] font-bold">
                    {(orgs.find((o) => o.id === activeOrg)?.name ?? "?")
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((w) => w[0])
                      .join("")
                      .toUpperCase()}
                  </div>
                  <SelectValue placeholder="Select organization…" />
                </div>
              </SelectTrigger>
              <SelectContent>
                {orgs.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {!activeOrg ? (
        <EmptyState
          icon={Brain}
          title="No organizations yet"
          description="Start an analysis to build your first organization profile. This workspace fills in automatically as intelligence is collected."
          action={
            <a
              href="/intelligence"
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02]"
            >
              <Sparkles className="h-4 w-4" /> New Analysis
            </a>
          }
        />
      ) : (
        <Tabs defaultValue="dashboard" className="space-y-6">
          <TabsList className="h-auto flex-wrap gap-1 rounded-xl border border-[var(--hairline)] bg-[var(--surface)]/60 p-1">
            <PremiumTab value="dashboard" icon={Activity}>
              Overview
            </PremiumTab>
            <PremiumTab value="recommendations" icon={Lightbulb}>
              Recommendations
            </PremiumTab>
            <PremiumTab value="debate" icon={Scale}>
              Conflicting Intelligence
            </PremiumTab>
            <PremiumTab value="run" icon={Brain}>
              Investigation Templates
            </PremiumTab>
            <PremiumTab value="refresh" icon={Sparkles}>
              Refresh Intelligence
            </PremiumTab>
            <PremiumTab value="search" icon={SearchIcon}>
              Search
            </PremiumTab>
          </TabsList>

          {/* ---------------- Overview ---------------- */}
          <TabsContent value="dashboard" className="space-y-6 focus-visible:outline-none">
            {isError ? (
              <Panel className="p-16 text-center text-sm text-rose-400">
                Couldn't load the dashboard. Please retry.
              </Panel>
            ) : isLoading || !dash ? (
              <DashboardSkeleton />
            ) : (
              <>
                <ExecutiveBrief dash={dash} orgName={activeOrgName} />
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <KpiCard
                    i={0}
                    label="Verified Findings"
                    value={dash.counts.validated}
                    icon={ShieldCheck}
                    accent="150"
                    trend={[3, 5, 4, 6, 8, 7, dash.counts.validated || 1]}
                  />
                  <KpiCard
                    i={1}
                    label="Recommendations"
                    value={dash.counts.recommendations}
                    icon={Lightbulb}
                    accent="60"
                    trend={[1, 2, 2, 3, 3, 4, dash.counts.recommendations || 1]}
                  />
                  <KpiCard
                    i={2}
                    label="Conflicting Intelligence"
                    value={dash.counts.disputes_open}
                    icon={Scale}
                    accent="330"
                    trend={[2, 1, 3, 2, 1, 2, dash.counts.disputes_open || 1]}
                  />
                  <KpiCard
                    i={3}
                    label="Investigations"
                    value={dash.counts.runs}
                    icon={Activity}
                    accent="285"
                    trend={[1, 1, 2, 3, 4, 5, dash.counts.runs || 1]}
                  />
                </div>

                <CriticalAlerts alerts={alertData?.alerts ?? []} />
                <TopOpportunities recommendations={dash.recommendations ?? []} onOpen={openClaim} />
                <CompetitorChanges changes={competitorChanges ?? []} />

                <Reveal delay={120}>
                  <FilterBar
                    status={statusFilter}
                    onStatus={setStatusFilter}
                    playbook={playbookFilter}
                    onPlaybook={setPlaybookFilter}
                    since={sinceFilter}
                    onSince={setSinceFilter}
                  />
                </Reveal>

                <div className="grid gap-5 lg:grid-cols-2">
                  <Reveal delay={160}>
                    <InsightColumn
                      title="Verified Findings"
                      icon={ShieldCheck}
                      insights={dash.validated_insights}
                      onOpenClaim={openClaim}
                      emptyLabel="No verified findings yet — they appear here once sources are cross-checked after an analysis."
                    />
                  </Reveal>
                  <Reveal delay={200}>
                    <InsightColumn
                      title="Recommendations"
                      icon={Lightbulb}
                      insights={dash.recommendations}
                      onOpenClaim={openClaim}
                      emptyLabel="Recommendations appear once verified findings support them."
                    />
                  </Reveal>
                </div>

                <Reveal delay={240}>
                  <DisputeSummary disputes={dash.disputes} />
                </Reveal>
                <Reveal delay={280}>
                  <ResearchHistory runs={dash.research_history} />
                </Reveal>
              </>
            )}
          </TabsContent>

          <TabsContent value="recommendations" className="focus-visible:outline-none">
            {dash && (
              <RecommendationExplorer
                orgId={activeOrg}
                recommendations={dash.recommendations}
                onOpenClaim={openClaim}
              />
            )}
          </TabsContent>

          <TabsContent value="debate" className="focus-visible:outline-none">
            {dash && <DebateView orgId={activeOrg} disputes={dash.disputes} />}
          </TabsContent>

          <TabsContent value="run" className="space-y-4 focus-visible:outline-none">
            <Panel className="p-6">
              <h3 className="text-[15px] font-semibold">Investigation Templates</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Ready-made investigation types — each defines what to collect and how deep to go.
                Choose one, then launch it from New Analysis.
              </p>
              <div className="mt-5">
                <PlaybookSelector selected={runPlaybook} onSelect={setRunPlaybook} />
              </div>
            </Panel>
          </TabsContent>

          <TabsContent value="refresh" className="focus-visible:outline-none">
            <RefreshPanel orgId={activeOrg} />
          </TabsContent>

          <TabsContent value="search" className="focus-visible:outline-none">
            <Panel className="p-6">
              <GlobalSearch orgId={activeOrg} onOpenClaim={openClaim} />
            </Panel>
          </TabsContent>
        </Tabs>
      )}

      <FindingDetailDrawer
        findingId={claimDialog}
        open={!!claimDialog}
        onOpenChange={(v) => !v && setClaimDialog(null)}
        onSelectFinding={setClaimDialog}
      />
    </AppShell>
  );
}

function PremiumTab({
  value,
  icon: Icon,
  children,
}: {
  value: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <TabsTrigger
      value={value}
      className="gap-1.5 rounded-lg px-3.5 py-1.5 text-[13px] font-medium text-muted-foreground transition-all data-[state=active]:bg-[var(--surface-2)] data-[state=active]:text-foreground data-[state=active]:shadow-[0_1px_2px_rgba(0,0,0,0.25)]"
    >
      <Icon className="h-4 w-4" />
      {children}
    </TabsTrigger>
  );
}

function ExecutiveBrief({ dash, orgName }: { dash: DashboardView; orgName: string }) {
  const verified = dash.counts.validated;
  const actions = dash.counts.recommendations;
  const conflicts = dash.counts.disputes_open;
  const topAction = dash.recommendations?.[0];

  const headline =
    verified === 0 && actions === 0
      ? `No intelligence has been collected for ${orgName} yet. Run an investigation to build its profile.`
      : `We have verified ${verified} finding${verified === 1 ? "" : "s"} about ${orgName} and identified ${actions} recommended action${actions === 1 ? "" : "s"}.${
          conflicts > 0
            ? ` ${conflicts} item${conflicts === 1 ? "" : "s"} need${conflicts === 1 ? "s" : ""} your review because sources disagree.`
            : " No sources currently disagree."
        }`;

  return (
    <Panel className="p-5">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-fuchsia-200">
          <Sparkles className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
            Executive brief
          </h2>
          <p className="mt-1.5 text-[14px] leading-relaxed">{headline}</p>
          {topAction && (
            <p className="mt-2.5 text-[13px] text-muted-foreground">
              <span className="font-medium text-foreground">Start here:</span> {topAction.title}
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}

function KpiCard({
  label,
  value,
  icon: Icon,
  accent,
  trend,
  i,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  accent: string;
  trend: number[];
  i: number;
}) {
  const color = `oklch(0.72 0.16 ${accent})`;
  return (
    <Reveal delay={i * 60}>
      <Panel interactive className="group relative overflow-hidden p-5">
        <div
          className="absolute -right-6 -top-6 h-24 w-24 rounded-full opacity-[0.08] blur-2xl transition-opacity group-hover:opacity-20"
          style={{ background: color }}
        />
        <div className="flex items-start justify-between">
          <div
            className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]"
            style={{ color }}
          >
            <Icon className="h-[18px] w-[18px]" />
          </div>
          <Sparkline data={trend} />
        </div>
        <div className="mt-4">
          <div className="tabular text-[32px] font-semibold leading-none tracking-tight">
            {value}
          </div>
          <div className="mt-1.5 text-[13px] text-muted-foreground">{label}</div>
        </div>
      </Panel>
    </Reveal>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/60 p-5"
          >
            <div className="flex justify-between">
              <Skeleton className="h-10 w-10 rounded-xl" />
              <Skeleton className="h-7 w-24" />
            </div>
            <Skeleton className="mt-4 h-8 w-16" />
            <Skeleton className="mt-2 h-3 w-24" />
          </div>
        ))}
      </div>
      <Skeleton className="h-14 w-full rounded-xl" />
      <div className="grid gap-5 lg:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}

function FilterBar({
  status,
  onStatus,
  playbook,
  onPlaybook,
  since,
  onSince,
}: {
  status: string;
  onStatus: (v: string) => void;
  playbook: string;
  onPlaybook: (v: string) => void;
  since: string;
  onSince: (v: string) => void;
}) {
  const active = status !== "all" || playbook !== "all" || since !== "";
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-[var(--hairline)] bg-[var(--surface)]/50 p-2.5">
      <span className="flex items-center gap-1.5 pl-1.5 text-[13px] font-medium text-muted-foreground">
        <Filter className="h-3.5 w-3.5" /> Filter
      </span>
      <Select value={status} onValueChange={onStatus}>
        <SelectTrigger className="h-8 w-36 rounded-lg border-[var(--hairline)] bg-[var(--surface-2)] text-[13px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All findings</SelectItem>
          <SelectItem value="validated">Verified</SelectItem>
          <SelectItem value="unreviewed">Under review</SelectItem>
          <SelectItem value="deferred">Deferred</SelectItem>
          <SelectItem value="resolved">Resolved</SelectItem>
          <SelectItem value="stale">Stale</SelectItem>
        </SelectContent>
      </Select>
      <Select value={playbook} onValueChange={onPlaybook}>
        <SelectTrigger className="h-8 w-40 rounded-lg border-[var(--hairline)] bg-[var(--surface-2)] text-[13px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All investigations</SelectItem>
          <SelectItem value="full_analysis">Executive Intelligence</SelectItem>
          <SelectItem value="competitor_scan">Competitive Intelligence</SelectItem>
          <SelectItem value="pricing_watch">Pricing Watch</SelectItem>
        </SelectContent>
      </Select>
      <Input
        type="date"
        value={since}
        onChange={(e) => onSince(e.target.value)}
        className="h-8 w-40 rounded-lg border-[var(--hairline)] bg-[var(--surface-2)] text-[13px]"
      />
      {active && (
        <button
          onClick={() => {
            onStatus("all");
            onPlaybook("all");
            onSince("");
          }}
          className="ml-auto rounded-lg px-2.5 py-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
        >
          Clear
        </button>
      )}
    </div>
  );
}

function InsightColumn({
  title,
  icon: Icon,
  insights,
  onOpenClaim,
  emptyLabel,
}: {
  title: string;
  icon: React.ElementType;
  insights: GraphInsight[];
  onOpenClaim: (id: string) => void;
  emptyLabel: string;
}) {
  const PREVIEW = 5;
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const visible = showAll ? insights : insights.slice(0, PREVIEW);
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Panel className="flex h-full flex-col p-5">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-fuchsia-300" />
        <h3 className="text-[15px] font-semibold">{title}</h3>
        <Badge variant="secondary" className="ml-auto rounded-md tabular">
          {insights.length}
        </Badge>
      </div>
      <div className="mt-4 space-y-2">
        {insights.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-muted-foreground">{emptyLabel}</p>
        ) : (
          visible.map((ins) => {
            const isOpen = expanded.has(ins.id);
            return (
              <div
                key={ins.id}
                className="rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 transition-colors hover:border-[color-mix(in_oklch,var(--primary)_30%,transparent)]"
              >
                <button
                  onClick={() => toggle(ins.id)}
                  aria-expanded={isOpen}
                  className="flex w-full items-start gap-3 p-3.5 text-left"
                >
                  <ChevronRight
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                      isOpen && "rotate-90",
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium leading-snug">{ins.title}</span>
                    {!isOpen && ins.body && (
                      <span className="mt-1 line-clamp-1 block text-[12.5px] text-muted-foreground">
                        {ins.body}
                      </span>
                    )}
                  </span>
                  <ConfidenceMeter value={ins.trust?.confidence ?? 0} size="sm" />
                </button>

                {isOpen && (
                  <div className="border-t border-[var(--hairline)] px-3.5 pb-3.5 pt-3">
                    {ins.body && (
                      <p className="text-[13px] leading-relaxed text-muted-foreground">
                        {ins.body}
                      </p>
                    )}
                    {ins.validation_note && (
                      <div className="mt-3 rounded-lg bg-[var(--surface-3)]/50 px-3 py-2">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          Why we trust this
                        </div>
                        <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
                          {ins.validation_note}
                        </p>
                      </div>
                    )}
                    {ins.claim_ids.length > 0 && (
                      <button
                        onClick={() => onOpenClaim(ins.claim_ids[0])}
                        className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-fuchsia-300 hover:underline"
                      >
                        <TrendingUp className="h-3 w-3" /> View supporting sources
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {insights.length > PREVIEW && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 w-full rounded-lg border border-[var(--hairline)] py-2 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-[var(--surface-2)]"
        >
          {showAll
            ? "Show less"
            : `Show all ${insights.length} · ${insights.length - PREVIEW} more`}
        </button>
      )}
    </Panel>
  );
}

function DisputeSummary({
  disputes,
}: {
  disputes: {
    open: GraphInsight[];
    deferred: GraphInsight[];
    resolved: GraphInsight[];
  };
}) {
  const cols: { label: string; items: GraphInsight[]; tone: string }[] = [
    { label: "open", items: disputes.open, tone: "text-fuchsia-300" },
    { label: "deferred", items: disputes.deferred, tone: "text-amber-300" },
    { label: "resolved", items: disputes.resolved, tone: "text-sky-300" },
  ];
  return (
    <Panel className="p-5">
      <div className="flex items-center gap-2">
        <Scale className="h-4 w-4 text-fuchsia-300" />
        <h3 className="text-[15px] font-semibold">Conflicting Intelligence</h3>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {cols.map(({ label, items }) => (
          <div
            key={label}
            className="rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/30 p-3.5"
          >
            <div className="flex items-center gap-2">
              <StatusBadge status={label} />
              <span className="tabular ml-auto text-lg font-semibold">{items.length}</span>
            </div>
            <div className="mt-2.5 space-y-1.5">
              {items.slice(0, 4).map((d) => (
                <p key={d.id} className="truncate text-[13px] text-muted-foreground">
                  {d.title}
                </p>
              ))}
              {items.length === 0 && <p className="text-[13px] text-muted-foreground/60">None</p>}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ResearchHistory({ runs }: { runs: DashboardRun[] }) {
  return (
    <Panel className="p-5">
      <div className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-sky-300" />
        <h3 className="text-[15px] font-semibold">Research History</h3>
      </div>
      <div className="mt-4">
        {runs.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-muted-foreground">
            No runs recorded yet.
          </p>
        ) : (
          <div className="divide-y divide-[var(--hairline)]">
            {runs.map((r) => (
              <div
                key={r.run_id}
                className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      r.status === "completed" ? "bg-emerald-400" : "bg-amber-400",
                    )}
                  />
                  {r.playbook && (
                    <Badge variant="secondary" className="rounded-md text-[10px] capitalize">
                      {r.playbook.id.replace(/_/g, " ")}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-3 text-[12px] text-muted-foreground">
                  {typeof r.summary.claims === "number" && (
                    <span className="tabular">{r.summary.claims} claims</span>
                  )}
                  {typeof r.summary.recommendations === "number" && (
                    <span className="tabular">{r.summary.recommendations} actions</span>
                  )}
                  <time className="tabular">{new Date(r.created_at).toLocaleDateString()}</time>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

type DashboardRun = {
  run_id: string;
  status: string;
  created_at: string;
  playbook: { id: string; version: string } | null;
  summary: Record<string, number>;
};

/* ==========================================================================
 * Mission Control sections. Each answers one question fast, uses compact rows
 * rather than article-sized cards, and stays silent when it has nothing real
 * to report (no invented urgency).
 * ======================================================================== */

const ALERT_TONE: Record<string, string> = {
  critical: "text-rose-300 bg-rose-500/12 border-rose-500/25",
  high: "text-amber-300 bg-amber-500/12 border-amber-500/25",
  medium: "text-sky-300 bg-sky-500/12 border-sky-500/25",
  low: "text-muted-foreground bg-[var(--surface-3)] border-[var(--hairline)]",
};

function MissionSection({
  title,
  icon: Icon,
  count,
  children,
}: {
  title: string;
  icon: React.ElementType;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-2">
      <h2 className="mb-2.5 flex items-center gap-2 px-1 text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" /> {title}
        {typeof count === "number" && count > 0 && (
          <span className="tabular rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px]">
            {count}
          </span>
        )}
      </h2>
      {children}
    </section>
  );
}

/** Only genuinely important intelligence — conflicts, competitor moves, site health. */
function CriticalAlerts({ alerts }: { alerts: CriticalAlert[] }) {
  return (
    <MissionSection title="Critical alerts" icon={AlertTriangle} count={alerts.length}>
      {alerts.length === 0 ? (
        <Panel className="px-4 py-3">
          <p className="text-[12.5px] text-muted-foreground">
            Nothing needs urgent attention. No unresolved conflicts, high-severity competitor moves,
            or serious website issues.
          </p>
        </Panel>
      ) : (
        <div className="space-y-1.5">
          {alerts.map((a, i) => (
            <Panel
              key={`${a.kind}-${i}`}
              className={cn("flex items-center gap-3 border px-4 py-2.5", ALERT_TONE[a.severity])}
            >
              <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase">
                {a.severity}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-foreground">{a.title}</div>
                <div className="truncate text-[11.5px] text-muted-foreground">{a.detail}</div>
              </div>
              <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:block">
                {a.action}
              </span>
            </Panel>
          ))}
        </div>
      )}
    </MissionSection>
  );
}

/** Highest-value actions, as compact rows with confidence and next step. */
function TopOpportunities({
  recommendations,
  onOpen,
}: {
  recommendations: GraphInsight[];
  onOpen: (id: string) => void;
}) {
  const top = [...recommendations]
    .sort((a, b) => (b.trust?.confidence ?? 0) - (a.trust?.confidence ?? 0))
    .slice(0, 3);

  return (
    <MissionSection title="Top opportunities" icon={Lightbulb} count={recommendations.length}>
      {top.length === 0 ? (
        <Panel className="px-4 py-3">
          <p className="text-[12.5px] text-muted-foreground">
            No opportunities yet — they appear once an investigation produces recommendations.
          </p>
        </Panel>
      ) : (
        <div className="space-y-1.5">
          {top.map((r) => {
            const conf = r.trust?.confidence ?? 0;
            const priority = conf >= 0.7 ? "High" : conf >= 0.45 ? "Medium" : "Low";
            const clickable = r.claim_ids.length > 0;
            return (
              <Panel
                key={r.id}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5",
                  clickable &&
                    "cursor-pointer transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]",
                )}
                {...(clickable
                  ? { role: "button", tabIndex: 0, onClick: () => onOpen(r.claim_ids[0]) }
                  : {})}
              >
                <span className="shrink-0 rounded bg-fuchsia-500/12 px-1.5 py-0.5 text-[10px] font-semibold text-fuchsia-300">
                  {priority}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium">{r.title}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {r.claim_ids.length} supporting source
                    {r.claim_ids.length === 1 ? "" : "s"}
                    {clickable && " · view evidence"}
                  </div>
                </div>
                <ConfidenceMeter value={conf} size="sm" />
              </Panel>
            );
          })}
        </div>
      )}
    </MissionSection>
  );
}

/** Most important recent competitor intelligence, newest first. */
function CompetitorChanges({ changes }: { changes: CompetitorChange[] }) {
  const top = changes.slice(0, 4);
  return (
    <MissionSection title="Competitor changes" icon={Swords} count={changes.length}>
      {top.length === 0 ? (
        <Panel className="px-4 py-3">
          <p className="text-[12.5px] text-muted-foreground">
            No competitor changes detected. Pages under monitoring are compared against their
            baseline on each scan.
          </p>
        </Panel>
      ) : (
        <div className="space-y-1.5">
          {top.map((c) => (
            <Panel key={c.id} className="flex items-center gap-3 px-4 py-2.5">
              <span
                className={cn(
                  "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                  ALERT_TONE[c.severity] ?? ALERT_TONE.low,
                )}
              >
                {c.severity}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium">
                  {c.competitor_name}
                  <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                    {c.category}
                  </span>
                </div>
                <div className="truncate text-[11.5px] text-muted-foreground">{c.summary}</div>
              </div>
              <span className="shrink-0 text-[11px] text-muted-foreground">
                {new Date(c.detected_at).toLocaleDateString()}
              </span>
            </Panel>
          ))}
        </div>
      )}
    </MissionSection>
  );
}
