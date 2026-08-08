/** Verification history — how a finding was established and updated over time. */
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { TrustBadge } from "./TrustBadge";
import { fetchClaimTimeline, type TimelineEntry } from "@/services/intelligence";

const REASON_LABEL: Record<string, string> = {
  created: "Created",
  conflict_lost: "Superseded (conflict)",
  adjudicated: "Superseded (adjudicated)",
  resurrected: "Resurrected",
  reactivated_new_domain: "Reactivated (new source)",
  identity_v2_migration: "Merged (migration)",
  claim_merge: "Merged into entity",
  set_status: "Status changed",
};

function dotColor(entry: TimelineEntry): string {
  if (entry.reason === "created") return "bg-sky-400";
  if (entry.to === "active") return "bg-emerald-400";
  if (entry.to === "superseded") return "bg-rose-400";
  if (entry.to === "unsupported") return "bg-zinc-400";
  return "bg-slate-400";
}

export function ClaimTimelineDialog({
  claimId,
  open,
  onOpenChange,
}: {
  claimId: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["claim-timeline", claimId],
    queryFn: () => fetchClaimTimeline(claimId!),
    enabled: open && !!claimId,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Verification history</DialogTitle>
        </DialogHeader>
        {isError ? (
          <p className="py-10 text-center text-sm text-rose-400">
            Couldn't load this claim's timeline. Please try again.
          </p>
        ) : isLoading || !data ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-sm font-medium">{data.claim.statement}</p>
              <div className="mt-2 flex items-center gap-2">
                <TrustBadge trust={data.claim.trust} />
                <span className="text-xs text-muted-foreground">
                  status: {data.claim.status ?? "active"}
                </span>
              </div>
            </div>
            <ol className="relative ml-3 space-y-4 border-l pl-6">
              {data.timeline.map((entry, i) => (
                <li key={i} className="relative">
                  <span
                    className={`absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-background ${dotColor(entry)}`}
                  />
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="text-sm font-medium">
                      {REASON_LABEL[entry.reason] ?? entry.reason}
                    </p>
                    <time className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {new Date(entry.at).toLocaleString()}
                    </time>
                  </div>
                  {entry.from && (
                    <p className="text-xs text-muted-foreground">
                      {entry.from} → {entry.to}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
