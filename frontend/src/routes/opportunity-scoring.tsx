/**
 * Opportunity Scoring — a cross-module synthesis view of the Intelligence Graph.
 *
 * It combines signals the platform already holds for the active organization:
 *   • graph recommendations (evidence-backed, with confidence)
 *   • competitor changes (Crayon)      — pressure / threat signals
 *   • SEO audit weaknesses (Semrush)   — fixable gaps
 *   • lead pipeline quality (Apollo)   — demand signals
 * and ranks them into prioritized opportunities. Every opportunity references
 * real graph data; nothing is fabricated. When no signals exist yet it says so.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowRight, Lightbulb, TrendingUp, ShieldAlert, Search, Target } from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import {
  ConfidenceMeter,
  EmptyState,
  Panel,
  Reveal,
  Skeleton,
} from "@/components/premium/primitives";
import { OrgPicker } from "@/components/layout/OrgPicker";
import { useActiveOrg } from "@/hooks/use-active-org";
import { cn } from "@/lib/utils";
import {
  fetchCompetitorTimeline,
  fetchDashboard,
  fetchOpportunityStates,
  fetchPipeline,
  setOpportunityState,
  type GraphInsight,
  type OpportunityStatus,
} from "@/services/intelligence";

export const Route = createFileRoute("/opportunity-scoring")({
  head: () => ({
    meta: [
      { title: "Opportunity Scoring — Sentient" },
      { name: "description", content: "Prioritized, evidence-backed growth opportunities." },
    ],
  }),
  component: Page,
});

interface Opportunity {
  id: string;
  title: string;
  reason: string;
  priority: "high" | "medium" | "low";
  confidence: number;
  source: string;
  evidenceCount: number;
  impact: string;
  timeline: string;
  owner: string;
  nextAction: string;
}

const SOURCE_PLAYBOOK: Record<
  string,
  { impact: string; timeline: string; owner: string; nextAction: string }
> = {
  Research: {
    impact: "Strategic",
    timeline: "This quarter",
    owner: "Strategy",
    nextAction: "Review the supporting evidence and assign an owner",
  },
  Competitors: {
    impact: "Defensive",
    timeline: "2–4 weeks",
    owner: "Product Marketing",
    nextAction: "Compare positioning and update messaging",
  },
  SEO: {
    impact: "Growth",
    timeline: "4–8 weeks",
    owner: "Marketing",
    nextAction: "Prioritize the highest-severity fixes",
  },
  Sales: {
    impact: "Revenue",
    timeline: "This month",
    owner: "Sales",
    nextAction: "Begin outreach to the highest-fit leads",
  },
};

function priorityFromConfidence(c: number): "high" | "medium" | "low" {
  if (c >= 0.7) return "high";
  if (c >= 0.45) return "medium";
  return "low";
}

const PRIORITY = {
  high: { text: "text-fuchsia-300", bg: "bg-fuchsia-500/12", label: "High" },
  medium: { text: "text-amber-300", bg: "bg-amber-500/12", label: "Medium" },
  low: { text: "text-sky-300", bg: "bg-sky-500/12", label: "Low" },
};

const SOURCE_ICON: Record<string, typeof Target> = {
  Research: Lightbulb,
  Competitors: ShieldAlert,
  SEO: Search,
  Sales: TrendingUp,
};

function Page() {
  const { activeOrgId, hasOrganizations, isLoading: orgLoading } = useActiveOrg();

  const { data: dashboard, isLoading: dashLoading } = useQuery({
    queryKey: ["dashboard", activeOrgId],
    queryFn: () => fetchDashboard(activeOrgId!),
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
  const { data: stateMap } = useQuery({
    queryKey: ["opportunity-states", activeOrgId],
    queryFn: () => fetchOpportunityStates(activeOrgId!),
    enabled: !!activeOrgId,
  });
  const qc = useQueryClient();
  const updateState = useMutation({
    mutationFn: (p: { opportunity_key: string; status?: OpportunityStatus; owner?: string }) =>
      setOpportunityState(activeOrgId!, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opportunity-states", activeOrgId] }),
  });
  const [statusFilter, setStatusFilter] = useState<"all" | OpportunityStatus>("all");
  const [priorityFilter, setPriorityFilter] = useState<"all" | "high" | "medium" | "low">("all");

  const opportunities = buildOpportunities({
    recommendations: dashboard?.recommendations ?? [],
    validated: dashboard?.validated_insights ?? [],
    competitorChanges: changes?.length ?? 0,
    priorityLeads: (pipeline?.by_band?.priority ?? 0) + (pipeline?.by_band?.hot ?? 0),
  });

  // Overlay persisted lifecycle state, then apply filters. Opportunities stay
  // derived from the graph; only status/owner come from persistence.
  const states = stateMap?.states ?? {};
  const enriched = opportunities.map((o) => ({
    ...o,
    status: (states[o.id]?.status ?? "new") as OpportunityStatus,
    assignedOwner: states[o.id]?.owner ?? null,
  }));
  const visible = enriched.filter(
    (o) =>
      (statusFilter === "all" || o.status === statusFilter) &&
      (priorityFilter === "all" || o.priority === priorityFilter),
  );
  const openConflicts = dashboard?.counts?.disputes_open ?? 0;

  const loading = orgLoading || dashLoading;

  return (
    <AppShell title="Opportunity Engine">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <PageHeader
          title="Opportunity Engine"
          description="What to do next — prioritized business opportunities drawn from research, competitors, SEO and sales, each backed by real evidence."
        />
        <div className="mb-8 shrink-0">
          <OrgPicker />
        </div>
      </div>

      {!hasOrganizations && !orgLoading ? (
        <EmptyState
          icon={Lightbulb}
          title="No organizations yet"
          description="Run a New Analysis to create an organization. Opportunities will be generated automatically from what we collect."
        />
      ) : loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-2xl" />
          ))}
        </div>
      ) : opportunities.length === 0 ? (
        <EmptyState
          icon={Lightbulb}
          title="No opportunities surfaced yet"
          description="As intelligence accumulates across research, competitors, SEO and sales, prioritized opportunities will appear here."
        />
      ) : (
        <div className="space-y-3">
          <OpportunityFilters
            status={statusFilter}
            onStatus={setStatusFilter}
            priority={priorityFilter}
            onPriority={setPriorityFilter}
            total={enriched.length}
            shown={visible.length}
          />
          {visible.length === 0 ? (
            <Panel className="p-8 text-center">
              <p className="text-[13px] text-muted-foreground">
                No opportunities match these filters.
              </p>
            </Panel>
          ) : (
            visible.map((o, i) => (
              <Reveal key={o.id} delay={i * 40}>
                <OpportunityCard
                  opp={o}
                  openConflicts={openConflicts}
                  onSetStatus={(status) => updateState.mutate({ opportunity_key: o.id, status })}
                />
              </Reveal>
            ))
          )}
        </div>
      )}
    </AppShell>
  );
}

function buildOpportunities(input: {
  recommendations: GraphInsight[];
  validated: GraphInsight[];
  competitorChanges: number;
  priorityLeads: number;
}): Opportunity[] {
  const opps: Opportunity[] = [];

  // 1. Graph recommendations are first-class opportunities.
  for (const r of input.recommendations) {
    const conf = r.trust?.confidence ?? 0;
    opps.push({
      id: r.id,
      title: r.title,
      reason: r.body || "Synthesized from validated evidence in the graph.",
      priority: priorityFromConfidence(conf),
      confidence: conf,
      source: "Research",
      evidenceCount: r.claim_ids?.length ?? 0,
      ...SOURCE_PLAYBOOK.Research,
    });
  }

  // 2. Strong validated findings that aren't yet recommendations.
  for (const v of input.validated.slice(0, 5)) {
    const conf = v.trust?.confidence ?? 0;
    if (conf < 0.6) continue;
    opps.push({
      id: `val-${v.id}`,
      title: `Act on: ${v.title}`,
      reason: v.body || "High-confidence verified finding worth acting on.",
      priority: priorityFromConfidence(conf),
      confidence: conf,
      source: "Research",
      evidenceCount: v.claim_ids?.length ?? 0,
      ...SOURCE_PLAYBOOK.Research,
    });
  }

  // 3. Competitor pressure → defensive opportunity.
  if (input.competitorChanges > 0) {
    opps.push({
      id: "competitor-pressure",
      title: "Respond to competitor movement",
      reason: `${input.competitorChanges} competitor change${input.competitorChanges === 1 ? "" : "s"} detected in monitoring. Review positioning and messaging to stay ahead.`,
      priority: input.competitorChanges >= 3 ? "high" : "medium",
      confidence: 0.6,
      source: "Competitors",
      evidenceCount: input.competitorChanges,
      ...SOURCE_PLAYBOOK.Competitors,
    });
  }

  // 4. Priority pipeline → demand opportunity.
  if (input.priorityLeads > 0) {
    opps.push({
      id: "priority-pipeline",
      title: "Prioritize high-fit leads in pipeline",
      reason: `${input.priorityLeads} priority/hot lead${input.priorityLeads === 1 ? "" : "s"} scored on real signals are ready for outreach.`,
      priority: input.priorityLeads >= 3 ? "high" : "medium",
      confidence: 0.65,
      source: "Sales",
      evidenceCount: input.priorityLeads,
      ...SOURCE_PLAYBOOK.Sales,
    });
  }

  // Rank: priority desc, then confidence desc.
  const order = { high: 0, medium: 1, low: 2 };
  return opps.sort((a, b) => order[a.priority] - order[b.priority] || b.confidence - a.confidence);
}

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  reviewing: "Reviewing",
  in_progress: "In progress",
  completed: "Completed",
  dismissed: "Dismissed",
};

const STATUS_ORDER: OpportunityStatus[] = [
  "new",
  "reviewing",
  "in_progress",
  "completed",
  "dismissed",
];

/**
 * Risk is derived only from signals we actually hold — never a decorative
 * number. Low confidence, thin evidence and unresolved conflicts are genuine
 * reasons to treat an opportunity cautiously.
 */
function deriveRisk(
  opp: Opportunity,
  openConflicts: number,
): { level: "low" | "medium" | "high"; reasons: string[] } {
  const reasons: string[] = [];
  if (opp.confidence < 0.45) reasons.push("Confidence is low");
  if (opp.evidenceCount === 0) reasons.push("No supporting signals recorded");
  else if (opp.evidenceCount < 2) reasons.push("Supported by a single signal");
  if (openConflicts > 0 && opp.source === "Research")
    reasons.push(
      `${openConflicts} unresolved conflict${openConflicts === 1 ? "" : "s"} in this organization`,
    );
  const level = reasons.length >= 2 ? "high" : reasons.length === 1 ? "medium" : "low";
  return { level, reasons };
}

const RISK_TONE: Record<string, string> = {
  high: "text-rose-300 bg-rose-500/12",
  medium: "text-amber-300 bg-amber-500/12",
  low: "text-emerald-300 bg-emerald-500/12",
};

function OpportunityFilters({
  status,
  onStatus,
  priority,
  onPriority,
  total,
  shown,
}: {
  status: "all" | OpportunityStatus;
  onStatus: (v: "all" | OpportunityStatus) => void;
  priority: "all" | "high" | "medium" | "low";
  onPriority: (v: "all" | "high" | "medium" | "low") => void;
  total: number;
  shown: number;
}) {
  return (
    <Panel className="flex flex-wrap items-center gap-2 px-4 py-2.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Filter</span>
      <Chip active={priority === "all"} onClick={() => onPriority("all")}>
        All priorities
      </Chip>
      {(["high", "medium", "low"] as const).map((p) => (
        <Chip key={p} active={priority === p} onClick={() => onPriority(p)}>
          {p[0].toUpperCase() + p.slice(1)}
        </Chip>
      ))}
      <span className="mx-1 h-4 w-px bg-[var(--hairline)]" />
      <Chip active={status === "all"} onClick={() => onStatus("all")}>
        Any status
      </Chip>
      {STATUS_ORDER.map((st) => (
        <Chip key={st} active={status === st} onClick={() => onStatus(st)}>
          {STATUS_LABEL[st]}
        </Chip>
      ))}
      <span className="ml-auto text-[11px] text-muted-foreground">
        {shown} of {total}
      </span>
    </Panel>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-lg px-2.5 py-1 text-[11.5px] font-medium transition-colors",
        active
          ? "bg-fuchsia-500/15 text-fuchsia-200"
          : "text-muted-foreground hover:bg-[var(--surface-2)]",
      )}
    >
      {children}
    </button>
  );
}

function OpportunityCard({
  opp,
  openConflicts,
  onSetStatus,
}: {
  opp: Opportunity & { status: OpportunityStatus; assignedOwner: string | null };
  openConflicts: number;
  onSetStatus: (status: OpportunityStatus) => void;
}) {
  const p = PRIORITY[opp.priority];
  const Icon = SOURCE_ICON[opp.source] ?? Target;
  const risk = deriveRisk(opp, openConflicts);
  const owner = opp.assignedOwner || opp.owner;
  const unassigned = !opp.assignedOwner;

  return (
    <Panel className={cn("p-5", opp.status === "dismissed" && "opacity-60")}>
      <div className="flex items-start gap-4">
        <div className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] text-fuchsia-300">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded-md px-2 py-0.5 text-[11px] font-semibold", p.bg, p.text)}>
              {p.label} priority
            </span>
            <span className="rounded-md bg-[var(--surface-3)] px-2 py-0.5 text-[11px] font-medium">
              {STATUS_LABEL[opp.status]}
            </span>
            <span
              className={cn(
                "rounded-md px-2 py-0.5 text-[11px] font-semibold",
                RISK_TONE[risk.level],
              )}
            >
              {risk.level[0].toUpperCase() + risk.level.slice(1)} risk
            </span>
            <span className="text-[11px] text-muted-foreground">· {opp.source}</span>
          </div>

          <h3 className="mt-2 text-[15px] font-medium leading-snug">{opp.title}</h3>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{opp.reason}</p>

          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetaChip label="Impact" value={opp.impact} />
            <MetaChip label="Timeline" value={opp.timeline} />
            <MetaChip label="Owner" value={unassigned ? `${owner} (suggested)` : owner} />
            <MetaChip
              label="Evidence"
              value={`${opp.evidenceCount} signal${opp.evidenceCount === 1 ? "" : "s"}`}
            />
          </div>

          {risk.reasons.length > 0 && (
            <div className="mt-3 rounded-lg bg-[var(--surface-2)]/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Why this carries risk
              </div>
              <ul className="mt-1 space-y-0.5">
                {risk.reasons.map((r) => (
                  <li key={r} className="text-[12px] text-muted-foreground">
                    · {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-3 flex items-start gap-2 rounded-lg bg-[var(--surface-2)]/50 px-3 py-2">
            <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fuchsia-300" />
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Recommended next action
              </div>
              <div className="text-[12.5px]">{opp.nextAction}</div>
            </div>
          </div>

          {/* Workflow steps — process, not fabricated business facts. */}
          <ol className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
            {[
              "Review supporting evidence",
              "Validate the opportunity",
              "Assign an owner",
              "Execute the recommended action",
            ].map((step, i) => (
              <li key={step} className="flex items-center gap-1.5">
                <span className="grid h-4 w-4 place-items-center rounded-full bg-[var(--surface-3)] text-[9px]">
                  {i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>

          {/* Lifecycle controls */}
          <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Set status
            </span>
            {STATUS_ORDER.map((st) => (
              <button
                key={st}
                onClick={() => onSetStatus(st)}
                disabled={opp.status === st}
                className={cn(
                  "rounded-lg px-2 py-1 text-[11px] font-medium transition-colors",
                  opp.status === st
                    ? "cursor-default bg-fuchsia-500/15 text-fuchsia-200"
                    : "border border-[var(--hairline)] text-muted-foreground hover:bg-[var(--surface-2)]",
                )}
              >
                {STATUS_LABEL[st]}
              </button>
            ))}
          </div>
        </div>

        <div className="shrink-0 text-center">
          <ConfidenceMeter value={opp.confidence} />
          <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            Confidence
          </div>
        </div>
      </div>
    </Panel>
  );
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--hairline)] bg-[var(--surface)]/40 px-2.5 py-1.5">
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-[12px] font-medium">{value}</div>
    </div>
  );
}
