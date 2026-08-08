import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { healthCheck, extractApiError } from "@/services/api";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — MABI" },
      { name: "description", content: "Configure your MABI workspace and backend connection." },
    ],
  }),
  component: Page,
});

function Page() {
  const apiUrl =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000";

  const [status, setStatus] = useState<"idle" | "ok" | "error" | "loading">("idle");

  async function ping() {
    setStatus("loading");
    try {
      await healthCheck();
      setStatus("ok");
      toast.success("Backend reachable");
    } catch (err) {
      setStatus("error");
      toast.error("Backend unreachable", { description: extractApiError(err) });
    }
  }

  return (
    <AppShell title="Settings">
      <PageHeader title="Settings" description="Manage your workspace and backend connection." />

      <div className="max-w-3xl space-y-6">
        <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-6">
          <h2 className="text-sm font-semibold">Backend endpoint</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Configured via <code>VITE_API_BASE_URL</code>.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <code className="rounded-lg border border-white/10 bg-background/60 px-3 py-2 text-xs">
              {apiUrl}
            </code>
            <Button variant="outline" size="sm" onClick={ping} disabled={status === "loading"}>
              {status === "loading" ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : status === "ok" ? (
                <CheckCircle2 className="mr-2 h-3.5 w-3.5 text-emerald-400" />
              ) : status === "error" ? (
                <XCircle className="mr-2 h-3.5 w-3.5 text-rose-400" />
              ) : null}
              Test connection
            </Button>
          </div>
        </div>

        <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-6">
          <h2 className="text-sm font-semibold">About</h2>
          <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
            Sentient is an enterprise business intelligence platform for a FastAPI backend. All
            content is generated live by the backend's LLM pipeline — this UI only renders whatever
            the API returns.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
