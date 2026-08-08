/** Trust/confidence pill — shared across the Intelligence Workspace. */
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TrustVector } from "@/services/intelligence";

export function TrustBadge({ trust }: { trust: TrustVector }) {
  const pct = Math.round((trust?.confidence ?? 0) * 100);
  const tone =
    pct >= 70
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : pct >= 45
        ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
        : "bg-rose-500/15 text-rose-300 border-rose-500/30";
  return (
    <Badge
      variant="outline"
      className={cn("gap-1 font-medium tabular-nums", tone)}
      title={`confidence ${pct}% · ${trust?.evidence_count ?? 0} sources · freshness ${Math.round((trust?.freshness ?? 0) * 100)}%`}
    >
      {pct}% confidence
    </Badge>
  );
}

const STATUS_TONE: Record<string, string> = {
  validated: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  unreviewed: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  rejected: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  stale: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  deferred: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  resolved: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  open: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30",
};

const STATUS_LABEL: Record<string, string> = {
  validated: "Verified",
  unreviewed: "Under review",
  rejected: "Not supported",
  stale: "Needs refresh",
  deferred: "Deferred",
  resolved: "Resolved",
  open: "Open conflict",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", STATUS_TONE[status] ?? STATUS_TONE.unreviewed)}
    >
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
