/**
 * Competitor Intelligence — powered by the real intelligence graph.
 * Each competitor is a living, evidence-backed profile (competitor_of edges →
 * entities → claims → evidence). Fields with no collected evidence honestly
 * read "Not yet collected" (Rule 2). Every claim drills into its timeline.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  ChevronRight,
  Database,
  ShieldAlert,
  Swords,
} from "lucide-react";
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
import { FindingDetailDrawer } from "@/components/analysis/FindingDetailDrawer";
import { cn } from "@/lib/utils";
import { fetchCompetitors, type Competitor } from "@/services/intelligence";

export const Route = createFileRoute("/competitors")({
  head: () => ({ meta: [{ title: "Competitors — Sentient Intelligence OS" }] }),
  component: CompetitorsPage,
});

// Topic buckets we know how to present; order matters for the profile layout.
const TOPIC_LABELS: Record<string, string> = {
  profile: "Overview",
  positioning: "Positioning",
  product: "Products & Features",
  pricing: "Pricing",
  technology: "Technology",
  market: "Market Position",
  competitors: "Competitive Set",
  strengths: "Strengths",
  weaknesses: "Weaknesses",
  general: "General",
};

function CompetitorsPage() {
  const { activeOrgId } = useActiveOrg();
  const [selected, setSelected] = useState<string | null>(null);
  const [claimDialog, setClaimDialog] = useState<string | null>(null);

  const activeOrg = activeOrgId;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["competitors", activeOrg],
    queryFn: () => fetchCompetitors(activeOrg!),
    enabled: !!activeOrg,
  });

  const competitors = useMemo(() => data?.competitors ?? [], [data]);
  const active = useMemo(
    () => competitors.find((c) => c.id === selected) ?? competitors[0] ?? null,
    [competitors, selected],
  );

  return (
    <AppShell title="Competitors">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <PageHeader
          title="Competitor Intelligence"
          description="Every competitor is a living, evidence-backed profile — tracked continuously and updated as new intelligence arrives."
        />
        <div className="mb-8 shrink-0">
          <OrgPicker />
        </div>
      </div>

      {!activeOrg ? (
        <EmptyState
          icon={Swords}
          title="No organizations to analyze yet"
          description="Run an analysis first. Competitors discovered during research appear here automatically as living profiles."
          action={
            <a
              href="/intelligence"
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02]"
            >
              New Analysis
            </a>
          }
        />
      ) : isError ? (
        <Panel className="p-16 text-center text-sm text-rose-400">
          Couldn't load competitor intelligence. Please retry.
        </Panel>
      ) : isLoading || !data ? (
        <CompetitorsSkeleton />
      ) : !data.has_data ? (
        <EmptyState
          icon={Swords}
          title="No competitors identified yet"
          description={`We haven't confirmed any competitors for ${data.organization.name} from public sources yet. Running an Executive or Competitive Intelligence investigation will populate this view as competitors are discovered and verified.`}
          action={
            <a
              href="/intelligence"
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02]"
            >
              Run an investigation
            </a>
          }
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          {/* Competitor rail */}
          <Reveal>
            <div className="space-y-2">
              {competitors.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelected(c.id)}
                  className={cn(
                    "group flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-all",
                    active?.id === c.id
                      ? "border-fuchsia-500/50 bg-fuchsia-500/[0.06]"
                      : "border-[var(--hairline)] bg-[var(--surface)]/50 hover:border-[color-mix(in_oklch,var(--primary)_30%,transparent)]",
                  )}
                >
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-[11px] font-bold ring-1 ring-[var(--hairline)]">
                    {c.name
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((w) => w[0])
                      .join("")
                      .toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium">{c.name}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {c.claim_count} findings · {c.evidence_count} sources
                    </div>
                  </div>
                  <ChevronRight
                    className={cn(
                      "h-4 w-4 shrink-0 text-muted-foreground transition-opacity",
                      active?.id === c.id ? "opacity-100" : "opacity-0 group-hover:opacity-100",
                    )}
                  />
                </button>
              ))}
            </div>
          </Reveal>

          {/* Competitor profile */}
          {active && (
            <Reveal delay={80}>
              <CompetitorProfile competitor={active} onOpenClaim={setClaimDialog} />
            </Reveal>
          )}
        </div>
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

function CompetitorProfile({
  competitor,
  onOpenClaim,
}: {
  competitor: Competitor;
  onOpenClaim: (id: string) => void;
}) {
  const topics = Object.keys(competitor.profile);
  // Present known topic buckets in a stable order, then any extras.
  const ordered = [
    ...Object.keys(TOPIC_LABELS).filter((t) => topics.includes(t)),
    ...topics.filter((t) => !(t in TOPIC_LABELS)),
  ];
  // Sections the spec expects but for which we may have no evidence yet.
  const expected = ["profile", "pricing", "market", "product"];
  const missing = expected.filter((t) => !topics.includes(t));

  return (
    <div className="space-y-5">
      <Panel className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-lg font-bold ring-1 ring-[var(--hairline)]">
              {competitor.name
                .split(/\s+/)
                .slice(0, 2)
                .map((w) => w[0])
                .join("")
                .toUpperCase()}
            </div>
            <div>
              <h2 className="text-[20px] font-semibold tracking-tight">{competitor.name}</h2>
              <div className="mt-1 flex items-center gap-3 text-[12px] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <Database className="h-3.5 w-3.5" /> {competitor.evidence_count} sources
                </span>
                <span className="inline-flex items-center gap-1">
                  <Building2 className="h-3.5 w-3.5" /> {competitor.claim_count} findings
                </span>
              </div>
            </div>
          </div>
          {competitor.confidence !== null && (
            <div className="text-right">
              <ConfidenceMeter value={competitor.confidence} />
              <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                Intelligence confidence
              </div>
            </div>
          )}
        </div>
      </Panel>

      {ordered.map((topic) => (
        <Panel key={topic} className="p-5">
          <h3 className="mb-3 text-[14px] font-semibold">{TOPIC_LABELS[topic] ?? topic}</h3>
          <div className="space-y-2">
            {competitor.profile[topic].map((claim) => (
              <button
                key={claim.id}
                onClick={() => onOpenClaim(claim.id)}
                className="group flex w-full items-start gap-3 rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 p-3.5 text-left transition-colors hover:border-[color-mix(in_oklch,var(--primary)_30%,transparent)]"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] leading-snug">{claim.statement}</p>
                  <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>
                      {claim.evidence_count} supporting source
                      {claim.evidence_count === 1 ? "" : "s"}
                    </span>
                    {claim.as_of && <span>· as of {claim.as_of.slice(0, 10)}</span>}
                  </div>
                </div>
                <ConfidenceMeter value={claim.confidence} size="sm" showLabel={false} />
              </button>
            ))}
          </div>
        </Panel>
      ))}

      {/* Honest "not yet collected" for expected-but-empty sections (Rule 2) */}
      {missing.length > 0 && (
        <Panel className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-[14px] font-semibold">Not yet collected</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {missing.map((t) => (
              <span
                key={t}
                className="rounded-lg border border-dashed border-[var(--hairline)] px-3 py-1.5 text-[12px] text-muted-foreground"
              >
                {TOPIC_LABELS[t] ?? t}
              </span>
            ))}
          </div>
          <p className="mt-3 text-[12px] text-muted-foreground">
            Run a deeper analysis or refresh this organization to collect evidence for these areas.
          </p>
        </Panel>
      )}
    </div>
  );
}

function CompetitorsSkeleton() {
  return (
    <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-xl" />
        ))}
      </div>
      <div className="space-y-5">
        <Skeleton className="h-28 rounded-2xl" />
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    </div>
  );
}
