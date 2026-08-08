/**
 * Reports — generate shareable executive reports from the active organization's
 * intelligence, and review report history. Every action here genuinely works
 * (Print, Copy, Markdown, HTML) — there are no placeholder buttons and no fake
 * formats. Report content is assembled from data the platform already holds.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  CheckCircle2,
  Clock,
  Printer,
  Copy,
  Download,
  Check,
  FileCode,
  FileDown,
  Table2,
  Presentation,
  Search as SearchIcon,
  Lightbulb,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Panel, Reveal, Skeleton } from "@/components/premium/primitives";
import { OrgPicker } from "@/components/layout/OrgPicker";
import { useActiveOrg } from "@/hooks/use-active-org";
import {
  datasetCsvUrl,
  fetchDashboard,
  reportPdfUrl,
  type DashboardView,
} from "@/services/intelligence";
import { buildMarkdown, buildHTML, REPORT_META, type ReportKind } from "@/lib/report-builder";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/reports")({
  head: () => ({
    meta: [
      { title: "Reports — Sentient" },
      { name: "description", content: "Generate and share executive reports." },
    ],
  }),
  component: Page,
});

const REPORT_ICONS: Record<ReportKind, React.ElementType> = {
  executive: FileText,
  board: Presentation,
  research: SearchIcon,
  opportunity: Lightbulb,
};

function Page() {
  const { activeOrgId, activeOrg, hasOrganizations, isLoading: orgLoading } = useActiveOrg();
  const [kind, setKind] = useState<ReportKind>("executive");

  const { data: dash, isLoading } = useQuery({
    queryKey: ["dashboard", activeOrgId, {}],
    queryFn: () => fetchDashboard(activeOrgId!),
    enabled: !!activeOrgId,
  });

  const history = dash?.research_history ?? [];
  const orgName = activeOrg?.name ?? "Organization";

  return (
    <AppShell title="Reports">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <PageHeader
          title="Reports"
          description="Generate a report you can share with executives — assembled from verified intelligence, ready to print or export."
        />
        <div className="mb-8 shrink-0">
          <OrgPicker />
        </div>
      </div>

      {!hasOrganizations && !orgLoading ? (
        <EmptyState
          icon={FileText}
          title="No reports yet"
          description="Run a New Analysis to generate your first report. Each report is assembled from verified intelligence."
        />
      ) : isLoading || orgLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-28 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : !dash ? null : (
        <div className="space-y-6">
          {/* Report type picker */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(Object.keys(REPORT_META) as ReportKind[]).map((k) => {
              const Icon = REPORT_ICONS[k];
              return (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  className={cn(
                    "rounded-2xl border p-4 text-left transition-all",
                    kind === k
                      ? "border-fuchsia-500/50 bg-fuchsia-500/[0.06]"
                      : "border-[var(--hairline)] bg-[var(--surface)]/50 hover:border-[color-mix(in_oklch,var(--primary)_25%,transparent)]",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-fuchsia-300" />
                    <span className="text-[13px] font-semibold">{REPORT_META[k].name}</span>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    {REPORT_META[k].description}
                  </p>
                  <div className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">
                    For {REPORT_META[k].audience}
                  </div>
                </button>
              );
            })}
          </div>

          <ReportPreview kind={kind} orgName={orgName} dash={dash} orgId={activeOrgId!} />

          {/* History */}
          <div>
            <h2 className="mb-3 px-1 text-[15px] font-semibold">Report history</h2>
            {history.length === 0 ? (
              <Panel className="p-6 text-center text-[13px] text-muted-foreground">
                Completed analyses appear here as report snapshots.
              </Panel>
            ) : (
              <div className="space-y-2">
                {history.map((run, i) => (
                  <Reveal key={run.run_id} delay={i * 30}>
                    <Panel className="flex items-center gap-4 p-4">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] text-fuchsia-300">
                        <FileText className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[14px] font-medium">
                            {run.playbook?.id
                              ? run.playbook.id
                                  .replace(/_/g, " ")
                                  .replace(/\b\w/g, (m) => m.toUpperCase())
                              : "Analysis"}
                          </span>
                          <span className="text-[11px] text-muted-foreground">· {orgName}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            {run.status === "completed" ? (
                              <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                            ) : (
                              <Clock className="h-3 w-3" />
                            )}
                            {run.status}
                          </span>
                          <span>·</span>
                          <span>{new Date(run.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                    </Panel>
                  </Reveal>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

function ReportPreview({
  kind,
  orgName,
  dash,
  orgId,
}: {
  kind: ReportKind;
  orgName: string;
  dash: DashboardView;
  orgId: string;
}) {
  const [copied, setCopied] = useState(false);
  const markdown = buildMarkdown(kind, orgName, dash);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      toast.success("Report copied to clipboard");
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Couldn't copy — your browser blocked clipboard access");
    }
  };

  const download = (format: "md" | "html") => {
    const content = format === "md" ? markdown : buildHTML(kind, orgName, dash);
    const blob = new Blob([content], {
      type: format === "md" ? "text/markdown" : "text/html",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const safe = orgName.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    a.href = url;
    a.download = `${safe}-${kind}-report.${format}`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`${format.toUpperCase()} downloaded`);
  };

  const print = () => {
    const html = buildHTML(kind, orgName, dash);
    const w = window.open("", "_blank");
    if (!w) {
      toast.error("Pop-up blocked — allow pop-ups to print");
      return;
    }
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 250);
  };

  return (
    <Panel className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--hairline)] bg-[var(--surface-2)]/40 px-4 py-3">
        <span className="text-[13px] font-semibold">{REPORT_META[kind].name} preview</span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <ActionButton
            icon={copied ? Check : Copy}
            label={copied ? "Copied" : "Copy"}
            onClick={copy}
          />
          <ActionButton icon={Download} label="Markdown" onClick={() => download("md")} />
          <ActionButton icon={FileCode} label="HTML" onClick={() => download("html")} />
          <ActionButton
            icon={FileDown}
            label="PDF"
            onClick={() => {
              window.open(reportPdfUrl(orgId, kind), "_blank", "noopener");
              toast.success("Preparing your PDF…");
            }}
          />
          <CsvMenu orgId={orgId} />
          <ActionButton icon={Printer} label="Print" onClick={print} primary />
        </div>
      </div>
      <div className="max-h-[440px] overflow-y-auto px-6 py-5">
        <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-foreground/90">
          {markdown}
        </pre>
      </div>
    </Panel>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  primary,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors",
        primary
          ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white hover:opacity-90"
          : "border border-[var(--hairline)] bg-[var(--surface)]/60 hover:bg-[var(--surface-2)]",
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {label}
    </button>
  );
}

/** Server-side CSV datasets. Only datasets the backend actually implements. */
const CSV_DATASETS: Array<{ id: string; label: string }> = [
  { id: "findings", label: "Findings" },
  { id: "recommendations", label: "Recommendations" },
  { id: "competitor_changes", label: "Competitor changes" },
  { id: "leads", label: "Leads" },
  { id: "website_audits", label: "Website audits" },
];

function CsvMenu({ orgId }: { orgId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <ActionButton icon={Table2} label="CSV" onClick={() => setOpen((v) => !v)} />
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-52 overflow-hidden rounded-xl border border-[var(--hairline)] bg-[var(--surface)] shadow-xl">
            {CSV_DATASETS.map((d) => (
              <button
                key={d.id}
                onClick={() => {
                  window.open(datasetCsvUrl(orgId, d.id), "_blank", "noopener");
                  toast.success(`Exporting ${d.label.toLowerCase()}…`);
                  setOpen(false);
                }}
                className="block w-full px-3 py-2 text-left text-[12.5px] transition-colors hover:bg-[var(--surface-2)]"
              >
                {d.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
