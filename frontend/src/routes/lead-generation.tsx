/**
 * Sales Intelligence — the Apollo module.
 * Discover a company → real enrichment (website + connectors) → evidence-based
 * lead score → CRM (pipeline stages, notes, tasks, activity) → AI outreach
 * grounded in the collected facts. Public contacts are shown honestly; emails
 * are never fabricated (marked "Not found"). Persisted + graph-linked.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  CheckCircle2,
  Circle,
  Mail,
  Plus,
  Sparkles,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Panel, Reveal, Skeleton } from "@/components/premium/primitives";
import { cn } from "@/lib/utils";
import {
  addLeadNote,
  addLeadTask,
  completeLeadTask,
  discoverLead,
  fetchLeadDetail,
  fetchLeads,
  fetchPipeline,
  generateEmail,
  moveLeadStage,
  PIPELINE_STAGES,
  type GeneratedEmail,
  type LeadDetail,
  type LeadSummary,
} from "@/services/intelligence";

export const Route = createFileRoute("/lead-generation")({
  head: () => ({ meta: [{ title: "Sales Intelligence — Sentient" }] }),
  component: LeadGenPage,
});

const BAND: Record<string, { text: string; bg: string; label: string }> = {
  priority: { text: "text-fuchsia-300", bg: "bg-fuchsia-500/12", label: "Priority" },
  hot: { text: "text-rose-300", bg: "bg-rose-500/12", label: "Hot" },
  warm: { text: "text-amber-300", bg: "bg-amber-500/12", label: "Warm" },
  cold: { text: "text-sky-300", bg: "bg-sky-500/12", label: "Cold" },
};

function LeadGenPage() {
  const qc = useQueryClient();
  const [band, setBand] = useState<string | undefined>();
  const [openLead, setOpenLead] = useState<string | null>(null);
  const [form, setForm] = useState({ companyName: "", domain: "" });

  const {
    data: leads,
    isLoading,
    isError: leadsError,
    refetch: refetchLeads,
  } = useQuery({
    queryKey: ["leads", band],
    queryFn: () => fetchLeads({ band }),
  });
  const { data: pipeline } = useQuery({ queryKey: ["pipeline"], queryFn: fetchPipeline });

  const discover = useMutation({
    mutationFn: () =>
      discoverLead({ companyName: form.companyName.trim(), domain: form.domain.trim() }),
    onSuccess: () => {
      setForm({ companyName: "", domain: "" });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });

  const canDiscover = form.companyName.trim() && form.domain.trim() && !discover.isPending;

  return (
    <AppShell title="Sales Intelligence">
      <PageHeader
        title="Sales Intelligence"
        description="Find and enrich companies with real signals, score them on evidence, and run outreach — all in one place."
      />

      {/* Discovery */}
      <Reveal>
        <Panel className="p-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
            <input
              value={form.companyName}
              onChange={(e) => setForm({ ...form, companyName: e.target.value })}
              placeholder="Company name"
              className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground/60"
            />
            <input
              value={form.domain}
              onChange={(e) => setForm({ ...form, domain: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && canDiscover && discover.mutate()}
              placeholder="company.com"
              className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground/60"
            />
            <button
              onClick={() => discover.mutate()}
              disabled={!canDiscover}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-medium transition-all",
                canDiscover
                  ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/20 hover:scale-[1.02]"
                  : "cursor-not-allowed bg-[var(--surface-2)] text-muted-foreground",
              )}
            >
              {discover.isPending ? (
                "Enriching…"
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" /> Discover
                </>
              )}
            </button>
          </div>
        </Panel>
      </Reveal>

      {/* Pipeline stats */}
      {pipeline && pipeline.has_data && (
        <Reveal delay={60}>
          <Panel className="mt-5 grid grid-cols-2 divide-x divide-[var(--hairline)] overflow-hidden sm:grid-cols-4">
            <Stat label="Total leads" value={pipeline.total_leads} />
            <Stat label="Avg score" value={pipeline.avg_score} />
            <Stat label="Contact rate" value={`${Math.round(pipeline.contact_rate * 100)}%`} />
            <Stat label="Conversion" value={`${Math.round(pipeline.conversion_rate * 100)}%`} />
          </Panel>
        </Reveal>
      )}

      {/* Filter + leads */}
      <div className="mt-6 flex items-center gap-2">
        <FilterChip label="All" active={!band} onClick={() => setBand(undefined)} />
        {(["priority", "hot", "warm", "cold"] as const).map((b) => (
          <FilterChip
            key={b}
            label={BAND[b].label}
            active={band === b}
            onClick={() => setBand(b)}
          />
        ))}
      </div>

      <div className="mt-4">
        {leadsError ? (
          <Panel className="p-8 text-center">
            <p className="text-[13.5px]">We couldn't load your leads.</p>
            <p className="mt-1 text-[12px] text-muted-foreground">
              This is a connection problem — no CRM data has been lost.
            </p>
            <button
              onClick={() => void refetchLeads()}
              className="mt-4 rounded-xl border border-[var(--hairline)] bg-[var(--surface-2)] px-4 py-2 text-[12.5px] font-medium transition-colors hover:bg-[var(--surface-3)]"
            >
              Try again
            </button>
          </Panel>
        ) : isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-xl" />
            ))}
          </div>
        ) : !leads || leads.length === 0 ? (
          <EmptyState
            icon={Building2}
            title="No leads yet"
            description="Discover your first company above. We'll fetch its real website signals, detect its tech stack, and score it on evidence."
          />
        ) : (
          <div className="space-y-2">
            {leads.map((l) => (
              <LeadRow key={l.id} lead={l} onOpen={() => setOpenLead(l.id)} />
            ))}
          </div>
        )}
      </div>

      {openLead && <LeadDrawer leadId={openLead} onClose={() => setOpenLead(null)} />}
    </AppShell>
  );
}

function LeadRow({ lead, onOpen }: { lead: LeadSummary; onOpen: () => void }) {
  const b = BAND[lead.score_band];
  return (
    <Panel interactive className="flex items-center gap-4 p-3.5" onClick={onOpen}>
      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-[12px] font-bold ring-1 ring-[var(--hairline)]">
        {lead.company_name.slice(0, 2).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium">{lead.company_name}</div>
        <div className="truncate text-[11px] text-muted-foreground">
          {[lead.domain, lead.industry, lead.employee_range].filter(Boolean).join(" · ") || "—"}
        </div>
      </div>
      <span
        className={cn("rounded-md px-2 py-0.5 text-[11px] font-semibold capitalize", b.bg, b.text)}
      >
        {lead.stage}
      </span>
      <div className="flex items-center gap-2">
        <span className={cn("rounded-md px-2 py-0.5 text-[11px] font-semibold", b.bg, b.text)}>
          {b.label}
        </span>
        <span className="tabular w-8 text-right text-[16px] font-semibold">{lead.score}</span>
      </div>
    </Panel>
  );
}

function LeadDrawer({ leadId, onClose }: { leadId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: lead } = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => fetchLeadDetail(leadId),
  });
  const [tab, setTab] = useState<"overview" | "crm" | "outreach">("overview");
  const [email, setEmail] = useState<GeneratedEmail | null>(null);
  const [emailErr, setEmailErr] = useState<string | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["lead", leadId] });
    qc.invalidateQueries({ queryKey: ["leads"] });
    qc.invalidateQueries({ queryKey: ["pipeline"] });
  };

  const stage = useMutation({
    mutationFn: (s: string) => moveLeadStage(leadId, s),
    onSuccess: refresh,
  });
  const note = useMutation({
    mutationFn: (b: string) => addLeadNote(leadId, b),
    onSuccess: refresh,
  });
  const task = useMutation({
    mutationFn: (t: string) => addLeadTask(leadId, t),
    onSuccess: refresh,
  });
  const doneTask = useMutation({
    mutationFn: (id: string) => completeLeadTask(id),
    onSuccess: refresh,
  });
  const genEmail = useMutation({
    mutationFn: () => generateEmail(leadId, "cold", true),
    onSuccess: (r) => {
      if (r.ok && r.email) {
        setEmail(r.email);
        setEmailErr(null);
      } else setEmailErr(r.error ?? "Unavailable");
      refresh();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--hairline)] bg-[var(--surface)] p-6 [animation:slidein_0.3s_cubic-bezier(0.16,1,0.3,1)]"
        onClick={(e) => e.stopPropagation()}
      >
        <style>{`@keyframes slidein{from{transform:translateX(24px);opacity:0}to{transform:none;opacity:1}}`}</style>
        {!lead ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-40 w-full rounded-xl" />
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-sm font-bold ring-1 ring-[var(--hairline)]">
                  {lead.company_name.slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <h2 className="text-[18px] font-semibold">{lead.company_name}</h2>
                  <div className="text-[12px] text-muted-foreground">
                    {lead.domain} · {lead.industry ?? "—"}
                  </div>
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-[var(--surface-2)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* score */}
            <div className="mt-5 flex items-center gap-4 rounded-2xl border border-[var(--hairline)] bg-[var(--surface-2)]/40 p-4">
              <div className="tabular text-4xl font-semibold">{lead.score}</div>
              <div>
                <span
                  className={cn(
                    "rounded-md px-2 py-0.5 text-[11px] font-semibold capitalize",
                    BAND[lead.score_band].bg,
                    BAND[lead.score_band].text,
                  )}
                >
                  {lead.score_band}
                </span>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  confidence {Math.round((lead.score_breakdown?.confidence ?? 0) * 100)}% ·
                  evidence-derived
                </div>
              </div>
            </div>

            {/* tabs */}
            <div className="mt-5 flex gap-2 border-b border-[var(--hairline)]">
              {(["overview", "crm", "outreach"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "px-3 py-2 text-[13px] font-medium capitalize transition-colors",
                    tab === t
                      ? "border-b-2 border-fuchsia-400 text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>

            {tab === "overview" && (
              <div className="mt-4 space-y-4">
                <div>
                  <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Score breakdown
                  </h3>
                  <div className="space-y-2">
                    {lead.score_breakdown?.factors?.map((f) => (
                      <div key={f.name}>
                        <div className="flex items-center justify-between text-[12.5px]">
                          <span>{f.name}</span>
                          <span className="tabular text-muted-foreground">
                            {f.points}/{f.max_points}
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500"
                            style={{ width: `${(f.points / f.max_points) * 100}%` }}
                          />
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">{f.detail}</p>
                      </div>
                    ))}
                  </div>
                  {(lead.score_breakdown?.confidence ?? 1) < 0.5 && (
                    <p className="mt-3 rounded-lg bg-amber-500/8 px-3 py-2 text-[11.5px] leading-relaxed text-amber-200/90">
                      This score is limited by <span className="font-medium">missing data</span>,
                      not necessarily poor fit. Verified contacts, revenue, and funding require a
                      data provider — connect one to enrich the score. No values are fabricated.
                    </p>
                  )}
                </div>
                <div>
                  <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Contacts
                  </h3>
                  {lead.contacts.length === 0 ? (
                    <p className="text-[12px] text-muted-foreground">
                      No public contacts collected. Emails are never fabricated — connect a provider
                      to enrich.
                    </p>
                  ) : (
                    lead.contacts.map((c) => (
                      <div
                        key={c.id}
                        className="flex items-center justify-between rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2 text-[12.5px]"
                      >
                        <div>
                          <div>{c.name}</div>
                          <div className="text-[11px] text-muted-foreground">{c.title}</div>
                        </div>
                        <span
                          className={cn(
                            "text-[11px]",
                            c.email_status === "found"
                              ? "text-emerald-300"
                              : "text-muted-foreground",
                          )}
                        >
                          {c.email_status === "found" ? c.email : "Email not found"}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {tab === "crm" && (
              <div className="mt-4 space-y-5">
                <div>
                  <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Pipeline stage
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {PIPELINE_STAGES.map((s) => (
                      <button
                        key={s}
                        onClick={() => stage.mutate(s)}
                        className={cn(
                          "rounded-lg px-2.5 py-1 text-[12px] capitalize transition-colors",
                          lead.stage === s
                            ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white"
                            : "border border-[var(--hairline)] bg-[var(--surface-2)] text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
                {/* Tasks — what needs doing, with due dates and status */}
                <CrmBlock
                  title="Tasks"
                  count={lead.tasks.filter((t) => !t.done).length}
                  countLabel="open"
                >
                  <QuickAdd label="Add task" onAdd={(v) => task.mutate(v)} />
                  {lead.tasks.length === 0 ? (
                    <CrmEmpty text="No tasks yet. Add one to track next steps for this account." />
                  ) : (
                    <div className="mt-2 space-y-1.5">
                      {[...lead.tasks]
                        .sort((a, b) => Number(a.done) - Number(b.done))
                        .map((t) => {
                          const overdue =
                            !t.done && t.due_date && new Date(t.due_date) < new Date();
                          return (
                            <button
                              key={t.id}
                              onClick={() => !t.done && doneTask.mutate(t.id)}
                              disabled={t.done}
                              className="flex w-full items-center gap-2.5 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2 text-left text-[12.5px] transition-colors hover:border-[color-mix(in_oklch,var(--primary)_30%,transparent)] disabled:cursor-default"
                            >
                              {t.done ? (
                                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                              ) : (
                                <Circle className="h-4 w-4 shrink-0 text-muted-foreground" />
                              )}
                              <span
                                className={cn(
                                  "min-w-0 flex-1 truncate",
                                  t.done && "text-muted-foreground line-through",
                                )}
                              >
                                {t.title}
                              </span>
                              {t.due_date && (
                                <span
                                  className={cn(
                                    "shrink-0 text-[11px]",
                                    overdue ? "text-rose-300" : "text-muted-foreground",
                                  )}
                                >
                                  {overdue ? "Overdue · " : "Due "}
                                  {new Date(t.due_date).toLocaleDateString()}
                                </span>
                              )}
                            </button>
                          );
                        })}
                    </div>
                  )}
                </CrmBlock>

                {/* Notes */}
                <CrmBlock title="Notes" count={lead.notes.length}>
                  <QuickAdd label="Add note" onAdd={(v) => note.mutate(v)} />
                  {lead.notes.length === 0 ? (
                    <CrmEmpty text="No notes yet." />
                  ) : (
                    <div className="mt-2 space-y-1.5">
                      {lead.notes.map((n) => (
                        <div
                          key={n.id}
                          className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/40 px-3 py-2"
                        >
                          <p className="text-[12.5px] leading-relaxed">{n.body}</p>
                          <div className="mt-1 text-[10.5px] text-muted-foreground">
                            {n.author || "You"} · {new Date(n.created_at).toLocaleString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CrmBlock>

                {/* Activity timeline — the account's full history */}
                <CrmBlock title="Activity timeline" count={lead.activities.length}>
                  {lead.activities.length === 0 ? (
                    <CrmEmpty text="No activity recorded yet. Stage changes, notes, tasks and outreach appear here." />
                  ) : (
                    <div className="relative mt-2 space-y-3 pl-5">
                      <div className="absolute bottom-1 left-[5px] top-1 w-px bg-[var(--hairline)]" />
                      {lead.activities.map((a) => {
                        const meta = ACTIVITY_KIND[a.kind] ?? ACTIVITY_KIND.default;
                        return (
                          <div key={a.id} className="relative">
                            <span
                              className={cn(
                                "absolute -left-5 top-1.5 h-2 w-2 rounded-full",
                                meta.dot,
                              )}
                            />
                            <div className="text-[12.5px] leading-snug">{a.summary}</div>
                            <div className="mt-0.5 text-[10.5px] text-muted-foreground">
                              {meta.label} · {new Date(a.created_at).toLocaleString()}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CrmBlock>
              </div>
            )}

            {tab === "outreach" && (
              <div className="mt-4 space-y-4">
                <button
                  onClick={() => genEmail.mutate()}
                  disabled={genEmail.isPending}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-[13px] font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02] disabled:opacity-60"
                >
                  <Mail className="h-3.5 w-3.5" />{" "}
                  {genEmail.isPending ? "Generating…" : "Generate AI email"}
                </button>
                {emailErr && <Panel className="p-4 text-[12.5px] text-amber-300">{emailErr}</Panel>}
                {email && (
                  <Panel className="p-4">
                    <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      Subject
                    </div>
                    <div className="mt-1 text-[14px] font-medium">{email.subject}</div>
                    <div className="mt-3 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90">
                      {email.body}
                    </div>
                    {email.personalization_notes.length > 0 && (
                      <div className="mt-3 border-t border-[var(--hairline)] pt-3">
                        <div className="text-[11px] text-muted-foreground">
                          Grounded in: {email.personalization_notes.join(", ")}
                        </div>
                      </div>
                    )}
                  </Panel>
                )}
                <p className="text-[11px] text-muted-foreground">
                  Emails are generated from this lead's real collected facts and can reference
                  competitor changes from monitoring — never invented.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function QuickAdd({ label, onAdd }: { label: string; onAdd: (v: string) => void }) {
  const [v, setV] = useState("");
  return (
    <div className="flex gap-2">
      <input
        value={v}
        onChange={(e) => setV(e.target.value)}
        placeholder={label}
        onKeyDown={(e) => {
          if (e.key === "Enter" && v.trim()) {
            onAdd(v.trim());
            setV("");
          }
        }}
        className="flex-1 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3 py-1.5 text-[12.5px] outline-none placeholder:text-muted-foreground/60"
      />
      <button
        onClick={() => {
          if (v.trim()) {
            onAdd(v.trim());
            setV("");
          }
        }}
        className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] px-2.5 text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-4 w-4" />
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="p-4">
      <div className="tabular text-[22px] font-semibold leading-none">{value}</div>
      <div className="mt-1.5 text-[11px] text-muted-foreground">{label}</div>
    </div>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors",
        active
          ? "bg-[var(--surface-3)] text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}

/* ==========================================================================
 * CRM building blocks — a real account workflow (tasks, notes, timeline)
 * rather than a notes list. All data comes from the existing CRM tables.
 * ======================================================================== */

const ACTIVITY_KIND: Record<string, { label: string; dot: string }> = {
  created: { label: "Lead created", dot: "bg-violet-400" },
  stage_change: { label: "Stage changed", dot: "bg-fuchsia-400" },
  note: { label: "Note added", dot: "bg-sky-400" },
  task: { label: "Task created", dot: "bg-amber-400" },
  task_complete: { label: "Task completed", dot: "bg-emerald-400" },
  email: { label: "Outreach generated", dot: "bg-emerald-400" },
  default: { label: "Activity", dot: "bg-muted-foreground" },
};

function CrmBlock({
  title,
  count,
  countLabel,
  children,
}: {
  title: string;
  count?: number;
  countLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
        {typeof count === "number" && count > 0 && (
          <span className="tabular rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px] normal-case">
            {count}
            {countLabel ? ` ${countLabel}` : ""}
          </span>
        )}
      </h3>
      {children}
    </div>
  );
}

function CrmEmpty({ text }: { text: string }) {
  return (
    <p className="rounded-lg border border-dashed border-[var(--hairline)] px-3 py-3 text-[12px] text-muted-foreground">
      {text}
    </p>
  );
}
