/**
 * FindingDetailDrawer — the executive detail view for a single finding.
 *
 * Opens from any finding across the product and answers, in business terms:
 * what the finding is, how confident we are, which real sources support it
 * (with type, authentication, reliability and links), and what it's used by
 * (recommendations & intelligence). No internal/graph terminology is exposed.
 */
import { useQuery } from "@tanstack/react-query";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ConfidenceMeter, Skeleton } from "@/components/premium/primitives";
import {
  Building2,
  ExternalLink,
  FileText,
  Lightbulb,
  Link2,
  ShieldCheck,
  Star,
  Swords,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchFindingDetail,
  fetchFindingRelated,
  type FindingSource,
} from "@/services/intelligence";

const SOURCE_TONE: Record<string, string> = {
  Government: "text-emerald-300 bg-emerald-500/12",
  Academic: "text-sky-300 bg-sky-500/12",
  News: "text-amber-300 bg-amber-500/12",
  "Official Repository": "text-violet-300 bg-violet-500/12",
  "Official Document": "text-violet-300 bg-violet-500/12",
  "Direct Measurement": "text-emerald-300 bg-emerald-500/12",
  Commercial: "text-slate-300 bg-slate-500/12",
  "Social / Community": "text-muted-foreground bg-[var(--surface-3)]",
  "User-Provided": "text-slate-300 bg-slate-500/12",
};

export function FindingDetailDrawer({
  findingId,
  open,
  onOpenChange,
  onSelectFinding,
}: {
  findingId: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Navigate the drawer to a related finding, keeping the drawer open. */
  onSelectFinding?: (id: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["finding", findingId],
    queryFn: () => fetchFindingDetail(findingId!),
    enabled: !!findingId && open,
  });
  // Cross-linking: what else this finding connects to, from existing graph
  // relationships only. Loads alongside the detail; never blocks it.
  const { data: related } = useQuery({
    queryKey: ["finding-related", findingId],
    queryFn: () => fetchFindingRelated(findingId!),
    enabled: !!findingId && open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto border-l border-[var(--hairline)] bg-[var(--surface)] sm:max-w-xl"
      >
        <SheetHeader>
          <SheetTitle className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Finding detail
          </SheetTitle>
        </SheetHeader>

        {isLoading || !data ? (
          <div className="mt-4 space-y-3">
            <Skeleton className="h-20 w-full rounded-xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
          </div>
        ) : (
          <div className="mt-3 space-y-6">
            {/* Statement + confidence */}
            <div>
              <p className="text-[16px] font-medium leading-snug">{data.statement}</p>
              <div className="mt-4 flex items-center gap-4 rounded-2xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 p-4">
                <ConfidenceMeter value={data.confidence} />
                <div>
                  <div className="text-[13px] font-medium">
                    {data.confidence >= 0.7
                      ? "High confidence"
                      : data.confidence >= 0.45
                        ? "Moderate confidence"
                        : "Low confidence"}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    Based on {data.source_count} supporting source
                    {data.source_count === 1 ? "" : "s"}
                    {data.corroboration > 0
                      ? ` · corroborated across ${Math.round(data.corroboration * 100)}% of checks`
                      : ""}
                  </div>
                </div>
              </div>
            </div>

            {/* What it means (business framing) */}
            <Section title="What this means" icon={ShieldCheck}>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                {businessMeaning(data.topic, data.confidence)}
              </p>
            </Section>

            {/* Supporting sources */}
            <Section title={`Supporting sources (${data.sources.length})`} icon={FileText}>
              {data.sources.length === 0 ? (
                <p className="text-[12.5px] text-muted-foreground">
                  No public sources are attached to this finding yet.
                </p>
              ) : (
                <div className="space-y-2">
                  {data.sources.map((s) => (
                    <SourceCard key={s.id} source={s} />
                  ))}
                </div>
              )}
            </Section>

            {/* Used by */}
            {(data.used_by.recommendations.length > 0 || data.used_by.insights.length > 0) && (
              <Section title="Used by" icon={Lightbulb}>
                <div className="space-y-2">
                  {data.used_by.recommendations.map((u) => (
                    <UsedByRow
                      key={u.id}
                      label="Recommendation"
                      title={u.title}
                      confidence={u.confidence}
                    />
                  ))}
                  {data.used_by.insights.map((u) => (
                    <UsedByRow
                      key={u.id}
                      label="Intelligence"
                      title={u.title}
                      confidence={u.confidence}
                    />
                  ))}
                </div>
              </Section>
            )}

            {/* Related intelligence (cross-linking) */}
            {related &&
              (related.recommendations.length > 0 ||
                related.competitors.length > 0 ||
                related.related_findings.length > 0) && (
                <Section title="Related intelligence" icon={Link2}>
                  <div className="space-y-3">
                    {related.recommendations.length > 0 && (
                      <RelatedGroup
                        label="Drives these recommendations"
                        items={related.recommendations.map((r) => ({
                          id: r.id,
                          text: r.title,
                          meta: `${Math.round(r.confidence * 100)}%`,
                        }))}
                        icon={Lightbulb}
                      />
                    )}
                    {related.competitors.length > 0 && (
                      <RelatedGroup
                        label="Related competitors"
                        items={related.competitors.map((c) => ({ id: c.id, text: c.name }))}
                        icon={Swords}
                      />
                    )}
                    {related.related_findings.length > 0 && (
                      <RelatedGroup
                        label="Related findings"
                        items={related.related_findings.map((f) => ({
                          id: f.id,
                          text: f.statement,
                          meta: `${Math.round(f.confidence * 100)}%`,
                        }))}
                        icon={FileText}
                        onSelect={onSelectFinding}
                      />
                    )}
                  </div>
                </Section>
              )}

            {/* Timestamps */}
            <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-[var(--hairline)] pt-4 text-[11px] text-muted-foreground">
              {data.as_of && <span>As of {fmt(data.as_of)}</span>}
              <span>First recorded {fmt(data.created_at)}</span>
              <span className="capitalize">
                Status: {data.status === "active" ? "Verified" : data.status}
              </span>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" /> {title}
      </h3>
      {children}
    </div>
  );
}

function SourceCard({ source }: { source: FindingSource }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      className="group block rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 p-3 transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate text-[13px] font-medium">{source.domain}</span>
            <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
          <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed text-muted-foreground">
            {source.preview}
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-semibold",
            SOURCE_TONE[source.source_type] ?? SOURCE_TONE.Commercial,
          )}
        >
          {source.source_type}
        </span>
        <Stars n={source.reliability_stars} />
        <span className="text-[10px] text-muted-foreground">
          {Math.round(source.authentication_score * 100)}% authenticated
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {fmt(source.extracted_at)}
        </span>
      </div>
    </a>
  );
}

function Stars({ n }: { n: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" title={`Reliability ${n}/5`}>
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className={cn(
            "h-3 w-3",
            i < n ? "fill-amber-400 text-amber-400" : "text-[var(--surface-3)]",
          )}
        />
      ))}
    </span>
  );
}

function UsedByRow({
  label,
  title,
  confidence,
}: {
  label: string;
  title: string;
  confidence: number;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2">
      <span className="rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
        {label}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12.5px]">{title}</span>
      <span className="tabular text-[11px] text-muted-foreground">
        {Math.round(confidence * 100)}%
      </span>
    </div>
  );
}

function businessMeaning(topic: string, confidence: number): string {
  const strength =
    confidence >= 0.7
      ? "This is well-supported and can inform decisions now."
      : confidence >= 0.45
        ? "This is a working conclusion; treat it as directional until further corroborated."
        : "This is an early signal and should be validated before acting.";
  const framing: Record<string, string> = {
    market: "It describes the market context the organization operates in.",
    pricing: "It reflects how the organization or its rivals price and package.",
    competitors: "It concerns the competitive landscape and rival positioning.",
    profile: "It establishes a core fact about the organization.",
    product: "It relates to the organization's products and capabilities.",
    positioning: "It reflects how the organization presents itself to the market.",
  };
  return `${framing[topic] ?? "It contributes to the organization's overall intelligence picture."} ${strength}`;
}

function fmt(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function RelatedGroup({
  label,
  items,
  icon: Icon,
  onSelect,
}: {
  label: string;
  items: Array<{ id: string; text: string; meta?: string }>;
  icon: React.ElementType;
  onSelect?: (id: string) => void;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </div>
      <div className="space-y-1.5">
        {items.map((it) => {
          const clickable = !!onSelect;
          return (
            <div
              key={it.id}
              {...(clickable
                ? {
                    role: "button",
                    tabIndex: 0,
                    onClick: () => onSelect!(it.id),
                    onKeyDown: (e: React.KeyboardEvent) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect!(it.id);
                      }
                    },
                  }
                : {})}
              className={cn(
                "flex items-center gap-2 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2",
                clickable &&
                  "cursor-pointer transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]",
              )}
            >
              <span className="min-w-0 flex-1 truncate text-[12.5px]">{it.text}</span>
              {it.meta && (
                <span className="tabular shrink-0 text-[11px] text-muted-foreground">
                  {it.meta}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
