/**
 * New Analysis — the launch experience.
 * Keyboard-first intake with playbook selection, then a cinematic live
 * research narrative, then a hand-off into the premium Workspace.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Clock, CornerDownLeft, Loader2, Sparkles } from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Kbd, Panel, Reveal } from "@/components/premium/primitives";
import { ResearchNarrative } from "@/components/premium/ResearchNarrative";
import { cn } from "@/lib/utils";
import { useActiveOrg } from "@/hooks/use-active-org";
import {
  fetchOrganizations,
  fetchPlaybooks,
  startAnalysisWithPlaybook,
  streamRunEvents,
  waitForRunCompletion,
  type PlaybookMeta,
  type RunEvent,
} from "@/services/intelligence";

export const Route = createFileRoute("/intelligence")({ component: IntelligencePage });

type Phase = "intake" | "clarify" | "running" | "completing";

function IntelligencePage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { setActiveOrgId } = useActiveOrg();
  const [phase, setPhase] = useState<Phase>("intake");
  const [message, setMessage] = useState("");
  const [priorMessage, setPriorMessage] = useState<string | undefined>();
  const [clarifyQuestion, setClarifyQuestion] = useState("");
  const [playbook, setPlaybook] = useState<string>("full_analysis");
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { data: playbooks } = useQuery({ queryKey: ["playbooks"], queryFn: fetchPlaybooks });
  const { data: orgs } = useQuery({ queryKey: ["organizations"], queryFn: fetchOrganizations });

  useEffect(() => {
    if (phase === "intake" || phase === "clarify") inputRef.current?.focus();
  }, [phase]);

  const submit = async () => {
    if (!message.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await startAnalysisWithPlaybook(message, playbook, priorMessage);
      if (res.status === "needs_clarification") {
        setClarifyQuestion(res.question);
        setPriorMessage(priorMessage ? `${priorMessage}\n${message}` : message);
        setMessage("");
        setPhase("clarify");
      } else {
        const orgId = res.organization_id;
        const runId = res.run_id;
        setEvents([]);
        setPhase("running");

        // Completion must be deterministic: always land on the organization we
        // just created, never the previously active one, and never hang.
        let settled = false;
        const finish = async (failed: boolean) => {
          if (settled) return;
          settled = true;

          if (orgId) setActiveOrgId(orgId); // open the NEW organization
          // Make sure the new organization and its intelligence are visible.
          await Promise.allSettled([
            qc.invalidateQueries({ queryKey: ["organizations"] }),
            qc.invalidateQueries({ queryKey: ["twin"] }),
            qc.invalidateQueries({ queryKey: ["dashboard"] }),
            qc.invalidateQueries({ queryKey: ["briefing"] }),
            qc.invalidateQueries({ queryKey: ["pipeline"] }),
            qc.invalidateQueries({ queryKey: ["website-audits"] }),
            qc.invalidateQueries({ queryKey: ["competitor-status"] }),
          ]);

          if (failed) {
            setError(
              "The investigation could not be completed. Any intelligence already collected has been saved.",
            );
            setTimeout(() => navigate({ to: "/workspace" as string }), 1200);
          } else {
            setPhase("completing");
            setTimeout(() => navigate({ to: "/workspace" as string }), 2600);
          }
        };

        streamRunEvents(
          runId,
          (e) => setEvents((prev) => [...prev, e]),
          (failed) => void finish(failed),
        );

        // Safety net: if the event stream never delivers a terminal event
        // (dropped connection, proxy timeout), poll the run instead of leaving
        // the user stuck on the loading screen.
        void waitForRunCompletion(runId).then(({ failed, timedOut }) => {
          if (timedOut) {
            if (!settled) {
              settled = true;
              setError(
                "This investigation is taking longer than expected. It is still running — check the Workspace shortly.",
              );
            }
            return;
          }
          void finish(failed);
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <AppShell title="New Analysis">
      <PageHeader
        title="New Analysis"
        description="Name a company or market to investigate. We collect the intelligence, verify it against real sources, and deliver an executive brief."
      />

      {error && (
        <Reveal>
          <div className="mb-5 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        </Reveal>
      )}

      {phase === "running" ? (
        <ResearchNarrative events={events} />
      ) : phase === "completing" ? (
        <CompletionSequence />
      ) : (
        <div className="mx-auto max-w-3xl space-y-6">
          {/* Intake composer */}
          <Reveal>
            <Panel className="overflow-hidden p-0">
              {phase === "clarify" && (
                <div className="border-b border-[var(--hairline)] bg-[var(--surface-2)]/40 px-5 py-3.5">
                  <div className="flex items-start gap-2.5">
                    <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-fuchsia-300" />
                    <p className="text-[13px] leading-relaxed">{clarifyQuestion}</p>
                  </div>
                </div>
              )}
              <textarea
                ref={inputRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={onKeyDown}
                rows={3}
                placeholder={
                  phase === "clarify"
                    ? "Add the missing detail…"
                    : "e.g. Analyze Stripe's competitive position in payments infrastructure"
                }
                className="w-full resize-none bg-transparent px-5 py-4 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/60"
              />
              <div className="flex items-center justify-between border-t border-[var(--hairline)] px-4 py-3">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Kbd>⌘</Kbd>
                  <Kbd>↵</Kbd>
                  <span className="ml-1">to run</span>
                </div>
                <button
                  onClick={submit}
                  disabled={!message.trim() || submitting}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[13px] font-medium transition-all",
                    message.trim() && !submitting
                      ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/20 hover:scale-[1.02]"
                      : "cursor-not-allowed bg-[var(--surface-2)] text-muted-foreground",
                  )}
                >
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      Run analysis <CornerDownLeft className="h-3.5 w-3.5" />
                    </>
                  )}
                </button>
              </div>
            </Panel>
          </Reveal>

          {/* Playbook selection */}
          {phase === "intake" && playbooks && (
            <Reveal delay={80}>
              <div>
                <div className="mb-2.5 flex items-center gap-2 px-1">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    Investigation Type
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {playbooks.map((pb) => (
                    <PlaybookTile
                      key={pb.id}
                      pb={pb}
                      selected={playbook === pb.id}
                      onSelect={() => setPlaybook(pb.id)}
                    />
                  ))}
                </div>
              </div>
            </Reveal>
          )}

          {/* Recent twins */}
          {phase === "intake" && (
            <Reveal delay={160}>
              {orgs && orgs.length > 0 ? (
                <div>
                  <div className="mb-2.5 px-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    Recent Organizations
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {orgs.slice(0, 6).map((o) => (
                      <button
                        key={o.id}
                        onClick={() => navigate({ to: "/workspace" as string })}
                        className="group flex items-center gap-3 rounded-xl border border-[var(--hairline)] bg-[var(--surface)]/50 px-3.5 py-3 text-left transition-all hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)] hover:bg-[var(--surface-2)]/60"
                      >
                        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-[11px] font-bold">
                          {o.name
                            .split(/\s+/)
                            .slice(0, 2)
                            .map((w) => w[0])
                            .join("")
                            .toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] font-medium">{o.name}</div>
                          {o.industry && (
                            <div className="truncate text-[11px] text-muted-foreground">
                              {o.industry}
                            </div>
                          )}
                        </div>
                        <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </Reveal>
          )}
        </div>
      )}
    </AppShell>
  );
}

const PLAYBOOK_META: Record<string, { name: string; duration: string; focus: string }> = {
  full_analysis: {
    name: "Executive Intelligence",
    duration: "5–10 min",
    focus: "Company, market, competitors, website & recommendations",
  },
  competitor_scan: {
    name: "Competitive Intelligence",
    duration: "3–6 min",
    focus: "Competitors, positioning, pricing & monitoring",
  },
  pricing_watch: {
    name: "Pricing Watch",
    duration: "2–4 min",
    focus: "Pricing, plans & packaging changes",
  },
};

function CompletionSequence() {
  const steps = [
    "Analysis complete",
    "Organization saved",
    "Building organization profile",
    "Generating executive brief",
    "Opening your workspace",
  ];
  const [active, setActive] = useState(0);
  useEffect(() => {
    const timers = steps.map((_, i) => setTimeout(() => setActive(i), i * 600));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-24 text-center">
      <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-fuchsia-500/25">
        <Check className="h-7 w-7 text-white" strokeWidth={2.5} />
      </div>
      <h2 className="mt-6 text-[18px] font-semibold">Intelligence ready</h2>
      <div className="mt-6 w-full space-y-2.5">
        {steps.map((s, i) => (
          <div
            key={s}
            className={cn(
              "flex items-center gap-3 rounded-xl border px-4 py-2.5 text-left text-[13px] transition-all duration-300",
              i <= active
                ? "border-[color-mix(in_oklch,var(--primary)_30%,transparent)] bg-[var(--surface-2)]/50 text-foreground"
                : "border-[var(--hairline)] text-muted-foreground/50",
            )}
          >
            {i < active ? (
              <Check className="h-4 w-4 text-emerald-400" strokeWidth={3} />
            ) : i === active ? (
              <Loader2 className="h-4 w-4 animate-spin text-fuchsia-300" />
            ) : (
              <div className="h-4 w-4 rounded-full border border-current opacity-40" />
            )}
            {s}
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaybookTile({
  pb,
  selected,
  onSelect,
}: {
  pb: PlaybookMeta;
  selected: boolean;
  onSelect: () => void;
}) {
  const meta = PLAYBOOK_META[pb.id] ?? {
    name: pb.id.replace(/_/g, " "),
    duration: "3–8 min",
    focus: pb.description,
  };
  return (
    <button
      onClick={onSelect}
      className={cn(
        "group relative rounded-2xl border p-4 text-left transition-all duration-200",
        selected
          ? "border-fuchsia-500/50 bg-fuchsia-500/[0.06] shadow-[0_0_0_1px_color-mix(in_oklch,var(--primary)_30%,transparent)]"
          : "border-[var(--hairline)] bg-[var(--surface)]/50 hover:border-[color-mix(in_oklch,var(--primary)_25%,transparent)]",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-semibold capitalize">{meta.name}</span>
        <span
          className={cn(
            "grid h-4 w-4 place-items-center rounded-full border transition-all",
            selected ? "border-fuchsia-400 bg-fuchsia-500 text-white" : "border-[var(--hairline)]",
          )}
        >
          {selected && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
        </span>
      </div>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground line-clamp-2">
        {meta.focus}
      </p>
      <div className="mt-3 flex items-center gap-1 text-[10px] text-muted-foreground">
        <Clock className="h-3 w-3" />
        {meta.duration}
      </div>
    </button>
  );
}
