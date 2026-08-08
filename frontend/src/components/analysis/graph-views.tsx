/**
 * Shared renderers for Intelligence Graph claims and insights.
 *
 * Every page that shows graph data uses these, so a claim looks and behaves the
 * same everywhere (evidence count, confidence, provenance) and there is one
 * place to evolve that presentation. This is part of turning the app into "one
 * graph, many views".
 */
import { ConfidenceMeter, Panel } from "@/components/premium/primitives";
import type { GraphClaim, GraphInsight } from "@/services/intelligence";

const KIND_LABEL: Record<string, string> = {
  fact: "Fact",
  event: "Update",
  metric: "Metric",
};

export function ClaimCard({ claim, onOpen }: { claim: GraphClaim; onOpen?: (id: string) => void }) {
  const sources = claim.evidence_ids.length;
  const clickable = !!onOpen;
  return (
    <Panel
      className={
        "p-4" +
        (clickable
          ? " cursor-pointer transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]"
          : "")
      }
      {...(clickable
        ? {
            role: "button",
            tabIndex: 0,
            onClick: () => onOpen!(claim.id),
            onKeyDown: (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen!(claim.id);
              }
            },
          }
        : {})}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] leading-snug">{claim.statement}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span className="rounded bg-[var(--surface-3)] px-1.5 py-0.5">
              {KIND_LABEL[claim.kind] ?? "Finding"}
            </span>
            <span>·</span>
            <span className={sources > 0 ? "" : "text-amber-300"}>
              {sources > 0
                ? `${sources} supporting source${sources === 1 ? "" : "s"}`
                : "Source pending"}
            </span>
            {claim.as_of && <span>· as of {claim.as_of}</span>}
            {claim.status && claim.status !== "active" && (
              <span className="rounded bg-amber-500/12 px-1.5 py-0.5 text-amber-300">
                {claim.status === "superseded" ? "updated" : claim.status}
              </span>
            )}
            {clickable && (
              <span className="ml-auto text-[10px] text-muted-foreground/70">View sources →</span>
            )}
          </div>
        </div>
        <ConfidenceMeter value={claim.trust?.confidence ?? 0} size="sm" />
      </div>
    </Panel>
  );
}

export function ClaimList({
  claims,
  emptyLabel = "No evidence collected",
  onOpen,
}: {
  claims: GraphClaim[];
  emptyLabel?: string;
  onOpen?: (id: string) => void;
}) {
  if (claims.length === 0) {
    return (
      <Panel className="p-6 text-center">
        <span className="text-[13px] text-muted-foreground">{emptyLabel}</span>
      </Panel>
    );
  }
  return (
    <div className="space-y-2.5">
      {claims.map((c) => (
        <ClaimCard key={c.id} claim={c} onOpen={onOpen} />
      ))}
    </div>
  );
}

const INSIGHT_KIND_LABEL: Record<string, string> = {
  finding: "Finding",
  recommendation: "Recommendation",
  dispute: "Conflict",
  signal: "Signal",
};

const REVIEW_LABEL: Record<string, string> = {
  validated: "Verified",
  unreviewed: "Under review",
  revised: "Revised",
  disputed: "Contested",
  resolved: "Resolved",
};

export function InsightCard({
  insight,
  onOpen,
}: {
  insight: GraphInsight;
  onOpen?: (id: string) => void;
}) {
  const supporting = insight.claim_ids.length;
  const clickable = !!onOpen && supporting > 0;
  const review = insight.debate_status ? (REVIEW_LABEL[insight.debate_status] ?? null) : null;
  return (
    <Panel
      className={
        "p-4" +
        (clickable
          ? " cursor-pointer transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]"
          : "")
      }
      {...(clickable
        ? {
            role: "button",
            tabIndex: 0,
            onClick: () => onOpen!(insight.claim_ids[0]),
            onKeyDown: (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen!(insight.claim_ids[0]);
              }
            },
          }
        : {})}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-[14px] font-medium">{insight.title}</h4>
          {insight.body && (
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
              {insight.body}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span className="rounded bg-[var(--surface-3)] px-1.5 py-0.5">
              {INSIGHT_KIND_LABEL[insight.kind] ?? "Finding"}
            </span>
            <span>·</span>
            <span>
              {supporting > 0
                ? `${supporting} supporting source${supporting === 1 ? "" : "s"}`
                : "Sources pending"}
            </span>
            {review && (
              <span
                className={
                  "rounded px-1.5 py-0.5 " +
                  (insight.debate_status === "validated"
                    ? "bg-emerald-500/12 text-emerald-300"
                    : insight.debate_status === "disputed"
                      ? "bg-amber-500/12 text-amber-300"
                      : "bg-[var(--surface-3)]")
                }
              >
                {review}
              </span>
            )}
            {clickable && (
              <span className="ml-auto text-[10px] text-muted-foreground/70">View sources →</span>
            )}
          </div>
        </div>
        <ConfidenceMeter value={insight.trust?.confidence ?? 0} size="sm" />
      </div>
    </Panel>
  );
}

/** Group a claim list by topic bucket (profile|market|competitors|pricing|…). */
export function groupClaimsByTopic(claims: GraphClaim[]): Record<string, GraphClaim[]> {
  const out: Record<string, GraphClaim[]> = {};
  for (const c of claims) {
    (out[c.topic] ??= []).push(c);
  }
  return out;
}
