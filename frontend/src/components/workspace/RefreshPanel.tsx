/** Refresh & Changes — manual refresh, live progress (SSE), change report. */
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/premium/primitives";
import { Badge } from "@/components/ui/badge";
import {
  fetchChanges,
  refreshTwin,
  streamRunEvents,
  type ChangeReport,
  type RunEvent,
} from "@/services/intelligence";

export function RefreshPanel({ orgId }: { orgId: string }) {
  const [state, setState] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [stage, setStage] = useState<string>("");
  const [report, setReport] = useState<ChangeReport | null>(null);
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => () => stopRef.current?.(), []); // close SSE on unmount

  async function onRefresh() {
    setState("running");
    setStage("starting…");
    setReport(null);
    const since = new Date().toISOString();
    try {
      const { run_id } = await refreshTwin(orgId);
      stopRef.current = streamRunEvents(
        run_id,
        (e: RunEvent) => {
          if (e.type === "research.stage") {
            setStage((e.payload.detail as string) || (e.payload.stage as string) || "working…");
          }
        },
        async (failed) => {
          if (failed) {
            setState("failed");
            return;
          }
          try {
            setReport(await fetchChanges(orgId, since));
          } catch {
            setReport(null);
          }
          setState("done");
        },
      );
    } catch {
      setState("failed");
    }
  }

  return (
    <Panel className="space-y-4 p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">Refresh Intelligence</h3>
          <p className="text-sm text-muted-foreground">
            Re-check key sources and update anything that has gone stale or is contested.
          </p>
        </div>
        <Button onClick={onRefresh} disabled={state === "running"}>
          {state === "running" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          Sync Intelligence
        </Button>
      </div>

      {state === "running" && (
        <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
          <span className="capitalize text-muted-foreground">{stage}</span>
        </div>
      )}

      {state === "failed" && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300">
          Refresh failed. Please try again.
        </div>
      )}

      {state === "done" && report && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{report.new_claims} new claims</Badge>
            <Badge variant="secondary">{report.supersessions.length} updated facts</Badge>
            <Badge variant="secondary">{report.signals.length} signals</Badge>
            <Badge variant="secondary">{report.disputes_opened.length} new conflicts</Badge>
          </div>
          {report.supersessions.length > 0 && (
            <div className="rounded-lg border p-3">
              <h4 className="mb-2 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-emerald-400">
                <Sparkles className="h-3.5 w-3.5" /> Newly discovered changes
              </h4>
              <ul className="space-y-1.5">
                {report.supersessions.map((s, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <span className="font-medium capitalize">
                      {s.predicate.replace(/_/g, " ")}:
                    </span>
                    <span className="text-muted-foreground line-through">{s.old_value}</span>
                    <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    <span className="font-medium text-emerald-300">{s.new_value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.new_claims === 0 && report.supersessions.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No changes detected — this organization's intelligence is up to date.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
