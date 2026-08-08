/** Conflicting Intelligence — where sources disagree on a fact. Shows both
 * versions with their supporting sources and the validation review outcome. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Loader2, Scale, Trophy } from "lucide-react";
import { ConfidenceMeter, Panel } from "@/components/premium/primitives";
import { StatusBadge } from "./TrustBadge";
import { fetchDisputeDetail, type GraphInsight } from "@/services/intelligence";

export function DebateView({
  orgId,
  disputes,
}: {
  orgId: string;
  disputes: {
    open: GraphInsight[];
    deferred: GraphInsight[];
    resolved: GraphInsight[];
  };
}) {
  const all = [...disputes.open, ...disputes.deferred, ...disputes.resolved];
  const [selected, setSelected] = useState<string | null>(all[0]?.id ?? null);

  if (all.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No conflicts. Your sources agree on the tracked facts.
      </p>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <div className="space-y-2">
        {all.map((d) => (
          <button
            key={d.id}
            onClick={() => setSelected(d.id)}
            className={`w-full rounded-lg border p-3 text-left text-sm hover:bg-muted/40 ${
              selected === d.id ? "border-fuchsia-500/50 bg-fuchsia-500/5" : ""
            }`}
          >
            <div className="flex items-center gap-2">
              <Scale className="h-4 w-4 shrink-0 text-fuchsia-400" />
              <span className="flex-1 font-medium">{d.title}</span>
            </div>
            <div className="mt-1.5">
              <StatusBadge status={d.debate_status} />
            </div>
          </button>
        ))}
      </div>
      {selected && <DisputeDetailPanel orgId={orgId} insightId={selected} />}
    </div>
  );
}

function DisputeDetailPanel({ orgId, insightId }: { orgId: string; insightId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dispute", orgId, insightId],
    queryFn: () => fetchDisputeDetail(orgId, insightId),
  });

  if (isError) {
    return (
      <Panel className="flex items-center justify-center py-16">
        <p className="text-sm text-rose-400">Couldn't load this conflict.</p>
      </Panel>
    );
  }
  if (isLoading || !data) {
    return (
      <Panel className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </Panel>
    );
  }

  // The reviewer rationale arrives as its own field (never inline in the body).
  const rationale = data.dispute.validation_note ? [data.dispute.validation_note] : [];

  return (
    <Panel className="space-y-4 p-6">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{data.dispute.title}</h3>
        <StatusBadge status={data.status} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {data.sides.map(({ claim, evidence }) => {
          const winner = data.winner_claim_id === claim.id;
          return (
            <div
              key={claim.id}
              className={`rounded-lg border p-3 ${
                winner ? "border-emerald-500/50 bg-emerald-500/5" : ""
              } ${claim.status === "superseded" ? "opacity-60" : ""}`}
            >
              <div className="flex items-center justify-between gap-2">
                {winner ? (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-400">
                    <Trophy className="h-3.5 w-3.5" /> Verified
                  </span>
                ) : (
                  <span className="text-xs capitalize text-muted-foreground">{claim.status}</span>
                )}
                <ConfidenceMeter value={claim.trust?.confidence ?? 0} size="sm" />
              </div>
              <p className="mt-2 text-sm font-medium">{claim.value ?? claim.statement}</p>
              <p className="mt-1 text-xs text-muted-foreground">{claim.statement}</p>
              <ul className="mt-2 space-y-1 border-t pt-2">
                {evidence.map((e) => (
                  <li key={e.id} className="flex items-center gap-1 text-xs">
                    <a
                      href={e.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-sky-400 hover:underline"
                    >
                      {e.domain}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      {rationale.length > 0 && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Validation review
          </h4>
          {rationale.map((r, i) => (
            <p key={i} className="text-sm">
              {r}
            </p>
          ))}
        </div>
      )}
    </Panel>
  );
}
