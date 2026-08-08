/** Recommendation Explorer — click a recommendation to expand the full
 * supporting sources behind each recommendation. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ExternalLink, Lightbulb, Loader2 } from "lucide-react";
import { ConfidenceMeter, Panel, Reveal } from "@/components/premium/primitives";
import { fetchRecommendationChain, type GraphInsight } from "@/services/intelligence";

export function RecommendationExplorer({
  orgId,
  recommendations,
  onOpenClaim,
}: {
  orgId: string;
  recommendations: GraphInsight[];
  onOpenClaim: (claimId: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (recommendations.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No recommendations yet. Run an analysis to generate them.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {recommendations.map((rec) => (
        <Panel key={rec.id} interactive className="overflow-hidden">
          <button
            className="flex w-full items-start gap-3 p-4 text-left hover:bg-muted/40"
            onClick={() => setExpanded(expanded === rec.id ? null : rec.id)}
          >
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
            <div className="flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{rec.title}</span>
                <ConfidenceMeter value={rec.trust?.confidence ?? 0} size="sm" />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{rec.body}</p>
            </div>
            <ChevronRight
              className={`mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
                expanded === rec.id ? "rotate-90" : ""
              }`}
            />
          </button>
          {expanded === rec.id && (
            <ChainDetail orgId={orgId} insightId={rec.id} onOpenClaim={onOpenClaim} />
          )}
        </Panel>
      ))}
    </div>
  );
}

function ChainDetail({
  orgId,
  insightId,
  onOpenClaim,
}: {
  orgId: string;
  insightId: string;
  onOpenClaim: (claimId: string) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["rec-chain", orgId, insightId],
    queryFn: () => fetchRecommendationChain(orgId, insightId),
  });

  if (isError) {
    return (
      <p className="border-t py-6 text-center text-sm text-rose-400">
        Couldn't load the evidence chain.
      </p>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="flex justify-center border-t py-6">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4 border-t border-[var(--hairline)] bg-[var(--surface-2)]/30 p-4">
      {data.supporting_insights.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Supporting insights
          </h4>
          <div className="space-y-2">
            {data.supporting_insights.map((ins) => (
              <div key={ins.id} className="rounded-md border bg-background/60 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{ins.title}</span>
                  <ConfidenceMeter value={ins.trust?.confidence ?? 0} size="sm" />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{ins.body}</p>
              </div>
            ))}
          </div>
        </section>
      )}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Supporting sources
        </h4>
        <div className="space-y-3">
          {data.claims.map(({ claim, evidence }) => (
            <div key={claim.id} className="rounded-md border bg-background/60 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm">{claim.statement}</p>
                <ConfidenceMeter value={claim.trust?.confidence ?? 0} size="sm" />
              </div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  className="rounded-md px-2 py-1 text-xs font-medium text-fuchsia-300 transition-colors hover:bg-fuchsia-500/10"
                  onClick={() => onOpenClaim(claim.id)}
                >
                  View timeline →
                </button>
                <span className="text-xs text-muted-foreground">
                  {evidence.length} source{evidence.length === 1 ? "" : "s"}
                </span>
              </div>
              {evidence.length > 0 && (
                <ul className="mt-2 space-y-1 border-t pt-2">
                  {evidence.map((e) => (
                    <li key={e.id} className="flex items-center gap-2 text-xs">
                      <a
                        href={e.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-sky-400 hover:underline"
                      >
                        {e.domain}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                      <span className="truncate text-muted-foreground">{e.title}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
