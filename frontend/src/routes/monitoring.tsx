/**
 * Competitor Monitoring — the Crayon module.
 * Monitor a competitor URL → snapshot & diff over time → real change timeline,
 * severity-ranked alerts, and an executive report. Every change is detected
 * from measured page signals — never fabricated. First scan sets a baseline.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  CheckCircle2,
  Circle,
  Clock,
  DollarSign,
  FileText,
  Globe,
  MessageSquare,
  Radar,
  Sparkles,
  Cpu,
} from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Panel, Reveal, Skeleton } from "@/components/premium/primitives";
import { OrgPicker } from "@/components/layout/OrgPicker";
import { useActiveOrg } from "@/hooks/use-active-org";
import { cn } from "@/lib/utils";
import {
  acknowledgeChange,
  fetchCompetitorAlerts,
  fetchCompetitorReport,
  fetchCompetitorTimeline,
  fetchMonitoringActivity,
  fetchMonitoringStatus,
  monitorCompetitor,
  type CompetitorChange,
  type MonitoringEvent,
  type MonitoringStatus,
  type WatchedUrl,
} from "@/services/intelligence";

export const Route = createFileRoute("/monitoring")({
  head: () => ({ meta: [{ title: "Competitor Monitoring — Sentient" }] }),
  component: MonitoringPage,
});

const CAT_ICON: Record<string, React.ElementType> = {
  pricing: DollarSign,
  messaging: MessageSquare,
  tech: Cpu,
  content: FileText,
  feature: Sparkles,
  release: Activity,
};
const SEV: Record<string, { text: string; dot: string; ring: string; label: string }> = {
  critical: {
    text: "text-rose-300",
    dot: "bg-rose-500",
    ring: "border-rose-500/40",
    label: "Critical",
  },
  high: { text: "text-amber-300", dot: "bg-amber-400", ring: "border-amber-500/30", label: "High" },
  medium: { text: "text-sky-300", dot: "bg-sky-400", ring: "border-sky-500/30", label: "Medium" },
  low: {
    text: "text-muted-foreground",
    dot: "bg-muted-foreground",
    ring: "border-[var(--hairline)]",
    label: "Low",
  },
};

function MonitoringPage() {
  const qc = useQueryClient();
  const { activeOrgId } = useActiveOrg();
  const activeOrg = activeOrgId;
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [banner, setBanner] = useState<string | null>(null);

  const {
    data: timeline,
    isError: timelineError,
    refetch: refetchTimeline,
  } = useQuery({
    queryKey: ["competitor-timeline", activeOrg],
    queryFn: () => fetchCompetitorTimeline(activeOrg!),
    enabled: !!activeOrg,
  });
  const { data: alerts } = useQuery({
    queryKey: ["competitor-alerts", activeOrg],
    queryFn: () => fetchCompetitorAlerts(activeOrg!),
    enabled: !!activeOrg,
  });
  const { data: report } = useQuery({
    queryKey: ["competitor-report", activeOrg],
    queryFn: () => fetchCompetitorReport(activeOrg!),
    enabled: !!activeOrg,
  });
  const { data: status } = useQuery({
    queryKey: ["competitor-status", activeOrg],
    queryFn: () => fetchMonitoringStatus(activeOrg!),
    enabled: !!activeOrg,
  });
  const { data: activity } = useQuery({
    queryKey: ["competitor-activity", activeOrg],
    queryFn: () => fetchMonitoringActivity(activeOrg!),
    enabled: !!activeOrg,
  });

  const monitor = useMutation({
    mutationFn: () =>
      monitorCompetitor({
        organizationId: activeOrg!,
        competitorName: name.trim(),
        url: url.trim(),
      }),
    onSuccess: (res) => {
      if (!res.ok) setBanner(res.error ?? "Could not reach that page.");
      else if (res.is_first)
        setBanner(`Baseline captured for ${name}. Future scans will detect changes.`);
      else
        setBanner(
          `${res.changes.length} change${res.changes.length === 1 ? "" : "s"} detected for ${name}.`,
        );
      setName("");
      setUrl("");
      qc.invalidateQueries({ queryKey: ["competitor-timeline"] });
      qc.invalidateQueries({ queryKey: ["competitor-alerts"] });
      qc.invalidateQueries({ queryKey: ["competitor-report"] });
      qc.invalidateQueries({ queryKey: ["competitor-status"] });
    },
  });

  const ack = useMutation({
    mutationFn: (id: string) => acknowledgeChange(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["competitor-alerts"] });
      qc.invalidateQueries({ queryKey: ["competitor-timeline"] });
    },
  });

  const canMonitor = !!activeOrg && name.trim() && url.trim() && !monitor.isPending;

  return (
    <AppShell title="Monitoring">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <PageHeader
          title="Competitor Monitoring"
          description="Track competitor pages over time. Each scan snapshots real signals and detects genuine changes — pricing, messaging, technology, content."
        />
        <div className="mb-8 shrink-0">
          <OrgPicker />
        </div>
      </div>

      {/* Monitor bar */}
      <Reveal>
        <Panel className="p-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr_auto]">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Competitor name"
              className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground/60"
            />
            <div className="flex items-center gap-2 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3">
              <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && canMonitor && monitor.mutate()}
                placeholder="https://competitor.com/pricing"
                className="flex-1 bg-transparent py-2 text-[13px] outline-none placeholder:text-muted-foreground/60"
              />
            </div>
            <button
              onClick={() => monitor.mutate()}
              disabled={!canMonitor}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-medium transition-all",
                canMonitor
                  ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/20 hover:scale-[1.02]"
                  : "cursor-not-allowed bg-[var(--surface-2)] text-muted-foreground",
              )}
            >
              {monitor.isPending ? (
                "Scanning…"
              ) : (
                <>
                  <Radar className="h-3.5 w-3.5" /> Scan now
                </>
              )}
            </button>
          </div>
          {banner && (
            <div className="mt-3 flex items-center gap-2 rounded-lg bg-[var(--surface-2)]/50 px-3 py-2 text-[12px] text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-fuchsia-300" /> {banner}
            </div>
          )}
        </Panel>
      </Reveal>

      {!activeOrg ? (
        <div className="mt-8">
          <EmptyState
            icon={Radar}
            title="No organizations yet"
            description="Run an analysis first, then monitor the competitors it discovers."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
          {/* Timeline */}
          <Reveal delay={60}>
            <section>
              {/* Monitored-pages status — shows baselines so a first scan never
                  leaves the page looking empty. */}
              <MonitoringOverview status={status} changeCount={timeline?.length ?? 0} />

              {status && status.watched.length > 0 && (
                <div className="mb-5">
                  <h2 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
                    <Radar className="h-4 w-4 text-muted-foreground" /> Monitored pages
                  </h2>
                  <div className="space-y-2">
                    {status.watched.map((w) => (
                      <WatchStatusCard key={w.url} watch={w} />
                    ))}
                  </div>
                </div>
              )}
              <h2 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
                <Activity className="h-4 w-4 text-muted-foreground" /> Change timeline
              </h2>
              {timelineError ? (
                <Panel className="p-8 text-center">
                  <p className="text-[13.5px]">We couldn't load monitoring activity.</p>
                  <p className="mt-1 text-[12px] text-muted-foreground">
                    This is a connection problem, not an absence of changes.
                  </p>
                  <button
                    onClick={() => void refetchTimeline()}
                    className="mt-4 rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] px-4 py-2 text-[12.5px] font-medium transition-colors hover:bg-[var(--surface-3)]"
                  >
                    Try again
                  </button>
                </Panel>
              ) : !timeline ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-20 rounded-2xl" />
                  ))}
                </div>
              ) : timeline.length === 0 ? (
                <Panel className="p-8 text-center text-sm text-muted-foreground">
                  {status && status.watched.length > 0
                    ? "Baselines captured and monitoring is active. Changes will appear here on the next scan that detects a difference."
                    : "No pages monitored yet. Add a competitor page above to capture a baseline; changes appear here on later scans."}
                </Panel>
              ) : (
                <div className="relative space-y-2.5 pl-6">
                  <div className="absolute bottom-2 left-[9px] top-2 w-px bg-[var(--hairline)]" />
                  {timeline.map((c) => (
                    <ChangeCard key={c.id} change={c} onAck={() => ack.mutate(c.id)} />
                  ))}
                </div>
              )}
              <ScanActivity events={activity?.events ?? []} />
            </section>
          </Reveal>

          {/* Right rail: alerts + report */}
          <div className="space-y-6">
            <Reveal delay={100}>
              <section>
                <h2 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
                  <Bell className="h-4 w-4 text-muted-foreground" /> Alerts
                  {alerts && alerts.length > 0 && (
                    <span className="tabular ml-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[11px] font-semibold text-rose-300">
                      {alerts.length}
                    </span>
                  )}
                </h2>
                {!alerts || alerts.length === 0 ? (
                  <Panel className="flex items-center gap-3 p-5">
                    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                    <span className="text-[13px] text-muted-foreground">No unread alerts.</span>
                  </Panel>
                ) : (
                  <div className="space-y-2">
                    {alerts.slice(0, 6).map((a) => (
                      <Panel key={a.id} className={cn("border-l-2 p-3.5", SEV[a.severity].ring)}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span
                                className={cn(
                                  "text-[10px] font-semibold uppercase tracking-wide",
                                  SEV[a.severity].text,
                                )}
                              >
                                {SEV[a.severity].label}
                              </span>
                              <span className="text-[11px] text-muted-foreground">
                                {a.competitor_name}
                              </span>
                            </div>
                            <p className="mt-1 text-[12.5px] leading-snug">{a.summary}</p>
                          </div>
                          <button
                            onClick={() => ack.mutate(a.id)}
                            className="shrink-0 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-[var(--surface-3)] hover:text-foreground"
                          >
                            Dismiss
                          </button>
                        </div>
                      </Panel>
                    ))}
                  </div>
                )}
              </section>
            </Reveal>

            {report && report.has_data && (
              <Reveal delay={140}>
                <section>
                  <h2 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
                    <FileText className="h-4 w-4 text-muted-foreground" /> Report
                  </h2>
                  <Panel className="p-5">
                    <div className="tabular text-3xl font-semibold">{report.total_changes}</div>
                    <div className="text-[12px] text-muted-foreground">total changes detected</div>
                    <div className="mt-4 space-y-1.5">
                      {Object.entries(report.by_category).map(([cat, n]) => {
                        const Icon = CAT_ICON[cat] ?? Activity;
                        return (
                          <div key={cat} className="flex items-center gap-2 text-[12.5px]">
                            <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                            <span className="capitalize">{cat}</span>
                            <span className="tabular ml-auto font-medium">{n}</span>
                          </div>
                        );
                      })}
                    </div>
                    {report.most_active.length > 0 && (
                      <div className="mt-4 border-t border-[var(--hairline)] pt-3">
                        <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                          Most active
                        </div>
                        {report.most_active.map((m) => (
                          <div
                            key={m.competitor}
                            className="flex items-center justify-between py-1 text-[12.5px]"
                          >
                            <span>{m.competitor}</span>
                            <span className="tabular text-muted-foreground">{m.changes}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </Panel>
                </section>
              </Reveal>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

function ChangeCard({ change, onAck }: { change: CompetitorChange; onAck: () => void }) {
  const Icon = CAT_ICON[change.category] ?? Activity;
  const sev = SEV[change.severity];
  return (
    <Panel className="relative p-4">
      <span
        className={cn(
          "absolute -left-[21px] top-5 h-2.5 w-2.5 rounded-full ring-4 ring-[var(--background)]",
          sev.dot,
        )}
      />
      <div className="flex items-start gap-3">
        <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] text-fuchsia-300">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={cn("text-[10px] font-semibold uppercase tracking-wide", sev.text)}>
              {sev.label}
            </span>
            <span className="text-[11px] capitalize text-muted-foreground">{change.category}</span>
            <span className="text-[11px] text-muted-foreground">· {change.competitor_name}</span>
            <span className="ml-auto text-[11px] text-muted-foreground">
              {new Date(change.detected_at).toLocaleDateString()}
            </span>
          </div>
          <p className="mt-1 text-[13.5px] font-medium leading-snug">{change.summary}</p>
          {(change.before || change.after) && (
            <div className="mt-2 space-y-1 text-[11.5px]">
              {change.before && (
                <div className="flex gap-2">
                  <span className="text-rose-300/80">−</span>
                  <span className="text-muted-foreground line-through decoration-rose-400/40">
                    {change.before}
                  </span>
                </div>
              )}
              {change.after && (
                <div className="flex gap-2">
                  <span className="text-emerald-300/80">+</span>
                  <span>{change.after}</span>
                </div>
              )}
            </div>
          )}
          {!change.acknowledged && (
            <button
              onClick={onAck}
              className="mt-2 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            >
              Acknowledge
            </button>
          )}
        </div>
      </div>
    </Panel>
  );
}

const WATCH_STATUS: Record<
  string,
  { label: string; text: string; dot: string; icon: typeof Circle }
> = {
  baseline: {
    label: "Baseline created · monitoring active",
    text: "text-sky-300",
    dot: "bg-sky-400",
    icon: Clock,
  },
  stable: {
    label: "Monitoring active · no changes yet",
    text: "text-emerald-300",
    dot: "bg-emerald-400",
    icon: CheckCircle2,
  },
  changes_detected: {
    label: "Changes detected",
    text: "text-amber-300",
    dot: "bg-amber-400",
    icon: Activity,
  },
};

function WatchStatusCard({ watch }: { watch: WatchedUrl }) {
  const s = WATCH_STATUS[watch.status] ?? WATCH_STATUS.baseline;
  const Icon = s.icon;
  return (
    <Panel className="flex items-center gap-3 p-3.5">
      <span className={cn("h-2 w-2 shrink-0 rounded-full", s.dot)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium">{watch.competitor_name}</span>
          <span className="truncate text-[11px] text-muted-foreground">{watch.url}</span>
        </div>
        <div className={cn("mt-0.5 flex items-center gap-1.5 text-[11px]", s.text)}>
          <Icon className="h-3 w-3" /> {s.label}
        </div>
      </div>
      <div className="shrink-0 text-right text-[11px] text-muted-foreground">
        <div>
          {watch.snapshot_count} scan{watch.snapshot_count === 1 ? "" : "s"}
        </div>
        {watch.last_scan && <div>{new Date(watch.last_scan).toLocaleDateString()}</div>}
      </div>
    </Panel>
  );
}

/**
 * Monitoring overview — answers "is monitoring actually working?" before the
 * user has to interpret an empty change list. States are deliberately distinct:
 * not configured / baseline created / active / changes detected.
 */
function MonitoringOverview({
  status,
  changeCount,
}: {
  status: MonitoringStatus | undefined;
  changeCount: number;
}) {
  if (!status) {
    return <Skeleton className="mb-5 h-24 rounded-2xl" />;
  }

  const watched = status.watched ?? [];
  const scans = status.total_snapshots ?? 0;
  const lastScan = watched
    .map((w) => w.last_scan)
    .filter(Boolean)
    .sort()
    .slice(-1)[0];

  let state: { label: string; tone: string; explain: string };
  if (watched.length === 0) {
    state = {
      label: "Not configured",
      tone: "text-muted-foreground bg-[var(--surface-3)]",
      explain: "No pages are being watched yet. Add a competitor page to capture a baseline.",
    };
  } else if (changeCount > 0) {
    state = {
      label: "Changes detected",
      tone: "text-amber-300 bg-amber-500/12",
      explain: `${changeCount} change${changeCount === 1 ? "" : "s"} detected since the baseline.`,
    };
  } else if (scans <= watched.length) {
    state = {
      label: "Baseline created",
      tone: "text-sky-300 bg-sky-500/12",
      explain:
        "Baselines are captured. Monitoring is active — the next scan will compare against them.",
    };
  } else {
    state = {
      label: "Monitoring active",
      tone: "text-emerald-300 bg-emerald-500/12",
      explain: "Monitoring is active. No material changes have been detected since the baseline.",
    };
  }

  return (
    <Panel className="mb-5 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className={cn("rounded-md px-2 py-0.5 text-[11px] font-semibold", state.tone)}>
          {state.label}
        </span>
        <p className="text-[13px] text-muted-foreground">{state.explain}</p>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <OverviewStat label="Pages watched" value={watched.length} />
        <OverviewStat label="Scans run" value={scans} />
        <OverviewStat label="Changes found" value={changeCount} />
        <OverviewStat
          label="Last scan"
          value={lastScan ? new Date(lastScan).toLocaleDateString() : "—"}
        />
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">
        Scans run when you trigger them or when an investigation refreshes this organization. There
        is no fixed schedule, so "next scan" is shown only once one is queued.
      </p>
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

const ACTIVITY_META: Record<string, { label: string; dot: string }> = {
  baseline_created: { label: "Baseline created", dot: "bg-sky-400" },
  scan_completed: { label: "Scan completed", dot: "bg-emerald-400" },
  change_detected: { label: "Change detected", dot: "bg-amber-400" },
};

/** Chronological proof that scanning happened, even when nothing changed. */
function ScanActivity({ events }: { events: MonitoringEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
        <Clock className="h-4 w-4 text-muted-foreground" /> Scan activity
      </h2>
      <Panel className="divide-y divide-[var(--hairline)] p-0">
        {events.slice(0, 12).map((e, i) => {
          const meta = ACTIVITY_META[e.kind] ?? ACTIVITY_META.scan_completed;
          return (
            <div key={`${e.at}-${i}`} className="flex items-start gap-3 px-4 py-3">
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", meta.dot)} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium">{meta.label}</span>
                  <span className="truncate text-[11px] text-muted-foreground">
                    {e.competitor_name}
                  </span>
                </div>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
                  {e.detail}
                </p>
              </div>
              <span className="shrink-0 text-[11px] text-muted-foreground">
                {new Date(e.at).toLocaleDateString()}
              </span>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}
