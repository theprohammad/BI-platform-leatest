/**
 * Market Research — a view of the Intelligence Graph, scoped to the active
 * organization. It reads persisted graph data (market-topic claims + insights)
 * rather than any ephemeral in-tab analysis result, so it stays populated after
 * a New Analysis completes and across refreshes. When the graph genuinely holds
 * no market evidence it says so — it never asks the user to re-run analysis.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Panel, Reveal, Skeleton } from "@/components/premium/primitives";
import { ClaimList, InsightCard } from "@/components/analysis/graph-views";
import { OrgPicker } from "@/components/layout/OrgPicker";
import { useActiveOrg } from "@/hooks/use-active-org";
import { fetchTwin, type GraphClaim, type GraphInsight } from "@/services/intelligence";
import { FindingDetailDrawer } from "@/components/analysis/FindingDetailDrawer";

export const Route = createFileRoute("/market-research")({
  head: () => ({
    meta: [
      { title: "Market Research — Sentient" },
      { name: "description", content: "Market size, growth, trends, opportunities and risks." },
    ],
  }),
  component: Page,
});

const MARKET_TOPICS = new Set(["market", "trends", "opportunity", "risk"]);

function Page() {
  const { activeOrgId, hasOrganizations, isLoading: orgLoading } = useActiveOrg();
  const [finding, setFinding] = useState<string | null>(null);

  const {
    data: twin,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["twin", activeOrgId],
    queryFn: () => fetchTwin(activeOrgId!),
    enabled: !!activeOrgId,
  });

  const marketClaims = (twin?.profile_claims ?? [])
    .concat(twin?.timeline ?? [])
    .filter((c) => MARKET_TOPICS.has(c.topic));
  const dedupClaims = Array.from(new Map(marketClaims.map((c) => [c.id, c])).values());
  const marketInsights = (twin?.insights ?? []).filter((i) =>
    /market|industry|trend|opportunit|risk|demand|growth/i.test(`${i.title} ${i.body}`),
  );

  return (
    <AppShell title="Market Research">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <PageHeader
          title="Market Research"
          description="What the market looks like — size, growth, trends, opportunities and risks, each backed by verified sources."
        />
        <div className="mb-8 shrink-0">
          <OrgPicker />
        </div>
      </div>

      {!hasOrganizations && !orgLoading ? (
        <EmptyState
          icon={TrendingUp}
          title="No organizations yet"
          description="Run a New Analysis to create your first organization. Its market intelligence will appear here automatically."
        />
      ) : isError ? (
        <LoadError onRetry={() => void refetch()} what="market intelligence" />
      ) : isLoading || orgLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
        </div>
      ) : (
        <div className="space-y-7">
          <MarketOverview insights={marketInsights} findings={dedupClaims} />

          {marketInsights.length > 0 && (
            <Reveal>
              <section>
                <h2 className="mb-2.5 px-1 text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Market signals
                </h2>
                <div className="space-y-2">
                  {marketInsights.map((i) => (
                    <InsightCard key={i.id} insight={i} onOpen={setFinding} />
                  ))}
                </div>
              </section>
            </Reveal>
          )}

          <Reveal delay={60}>
            <section>
              <h2 className="mb-2.5 flex items-center gap-2 px-1 text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
                Key findings
                {dedupClaims.length > 0 && (
                  <span className="tabular rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px]">
                    {dedupClaims.length}
                  </span>
                )}
              </h2>
              <ClaimList
                claims={dedupClaims}
                emptyLabel="No market evidence collected for this organization yet."
                onOpen={setFinding}
              />
            </section>
          </Reveal>

          {dedupClaims.length === 0 && marketInsights.length === 0 && (
            <Panel className="p-4">
              <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                Market data has not yet been collected for this organization. Market size,
                competitor landscape, and traffic estimates that require a commercial data provider
                will remain <span className="text-foreground">unavailable</span> until one is
                connected — they are never fabricated.
              </p>
            </Panel>
          )}
        </div>
      )}
      <FindingDetailDrawer
        findingId={finding}
        open={!!finding}
        onOpenChange={(v) => !v && setFinding(null)}
        onSelectFinding={setFinding}
      />
    </AppShell>
  );
}

/**
 * Market overview — the 10-second answer. Everything shown is counted from the
 * intelligence actually collected; no market metric is invented. Dated evidence
 * gives a real "most recent" signal instead of a fabricated trend.
 */
function MarketOverview({
  insights,
  findings,
}: {
  insights: GraphInsight[];
  findings: GraphClaim[];
}) {
  const all = [
    ...insights.map((i) => i.trust?.confidence ?? 0),
    ...findings.map((f) => f.trust?.confidence ?? 0),
  ];
  const avg = all.length ? all.reduce((a, b) => a + b, 0) / all.length : 0;
  const sources = findings.reduce((n, f) => n + f.evidence_ids.length, 0);
  const dated = findings
    .map((f) => f.as_of)
    .filter((d): d is string => !!d)
    .sort();
  const latest = dated.length ? dated[dated.length - 1] : null;

  if (insights.length === 0 && findings.length === 0) return null;

  return (
    <Panel className="p-5">
      <h2 className="text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
        Market overview
      </h2>
      <p className="mt-1.5 text-[13.5px] leading-relaxed">
        {insights.length > 0
          ? `${insights.length} market signal${insights.length === 1 ? "" : "s"} identified, supported by ${findings.length} verified finding${findings.length === 1 ? "" : "s"} drawn from ${sources} source${sources === 1 ? "" : "s"}.`
          : `${findings.length} verified finding${findings.length === 1 ? "" : "s"} collected from ${sources} source${sources === 1 ? "" : "s"}. No higher-level market signals have been synthesized yet.`}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <OverviewStat label="Market signals" value={insights.length} />
        <OverviewStat label="Verified findings" value={findings.length} />
        <OverviewStat label="Sources" value={sources} />
        <OverviewStat
          label="Avg confidence"
          value={all.length ? `${Math.round(avg * 100)}%` : "—"}
        />
      </div>
      {latest && (
        <p className="mt-3 text-[11px] text-muted-foreground">
          Most recent dated evidence: {latest.slice(0, 10)}
        </p>
      )}
    </Panel>
  );
}

function OverviewStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2.5">
      <div className="tabular text-[18px] font-semibold leading-none">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

/** Deliberate error state — never leave a failed load looking like "no data". */
function LoadError({ onRetry, what }: { onRetry: () => void; what: string }) {
  return (
    <Panel className="p-8 text-center">
      <p className="text-[13.5px]">We couldn't load {what}.</p>
      <p className="mt-1 text-[12px] text-muted-foreground">
        This is a connection problem, not an empty result — your intelligence is safe.
      </p>
      <button
        onClick={onRetry}
        className="mt-4 rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] px-4 py-2 text-[12.5px] font-medium transition-colors hover:bg-[var(--surface-3)]"
      >
        Try again
      </button>
    </Panel>
  );
}
