/**
 * Website & SEO Intelligence — the Semrush-class module.
 * Runs a REAL technical audit (fetch → analyze) and renders evidence-derived
 * scores, categorized issues with fixes, technical/on-page/tech-stack/security
 * panels, and audit history. Every number is measured from the actual page —
 * nothing fabricated. Data that needs a commercial provider (keyword volume,
 * backlinks, traffic) is explicitly marked unavailable rather than invented.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Code2,
  Globe,
  Image,
  Layers,
  Link2,
  Lock,
  Search,
  Share2,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { EmptyState, Panel, Reveal, Skeleton } from "@/components/premium/primitives";
import { cn } from "@/lib/utils";
import {
  fetchAuditHistory,
  runWebsiteAudit,
  type SeoAnalysis,
  type SeoAuditResult,
  type SeoIssue,
  type SeoScores,
} from "@/services/intelligence";

export const Route = createFileRoute("/website-audit")({
  head: () => ({ meta: [{ title: "SEO & Website Intelligence — Sentient" }] }),
  component: WebsiteAuditPage,
});

const SEV_ORDER = { high: 0, medium: 1, low: 2 } as const;
const SEV_STYLE: Record<string, { text: string; dot: string; label: string }> = {
  high: { text: "text-rose-300", dot: "bg-rose-500", label: "High" },
  medium: { text: "text-amber-300", dot: "bg-amber-400", label: "Medium" },
  low: { text: "text-sky-300", dot: "bg-sky-400", label: "Low" },
};

function WebsiteAuditPage() {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<SeoAuditResult | null>(null);

  const { data: history } = useQuery({
    queryKey: ["audit-history"],
    queryFn: () => fetchAuditHistory(),
  });

  const audit = useMutation({
    mutationFn: (u: string) => runWebsiteAudit(u),
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ["audit-history"] });
    },
  });

  const run = () => {
    if (url.trim()) audit.mutate(url.trim());
  };

  return (
    <AppShell title="SEO Intelligence">
      <PageHeader
        title="Website & SEO Intelligence"
        description="Run a real technical SEO audit — measured from the live page. Every issue is evidence-backed with a recommended fix."
      />

      {/* URL bar */}
      <Reveal>
        <Panel className="overflow-hidden p-0">
          <div className="flex items-center gap-3 px-4 py-3">
            <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              placeholder="example.com — enter any website to audit"
              className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground/60"
            />
            <button
              onClick={run}
              disabled={!url.trim() || audit.isPending}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[13px] font-medium transition-all",
                url.trim() && !audit.isPending
                  ? "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/20 hover:scale-[1.02]"
                  : "cursor-not-allowed bg-[var(--surface-2)] text-muted-foreground",
              )}
            >
              {audit.isPending ? (
                "Auditing…"
              ) : (
                <>
                  Run audit <ArrowRight className="h-3.5 w-3.5" />
                </>
              )}
            </button>
          </div>
        </Panel>
      </Reveal>

      {/* Result */}
      {audit.isPending ? (
        <div className="mt-6 space-y-4">
          <Skeleton className="h-40 w-full rounded-2xl" />
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
      ) : result ? (
        result.ok && result.analysis && result.scores ? (
          <AuditReport analysis={result.analysis} scores={result.scores} />
        ) : (
          <Reveal>
            <Panel className="mt-6 p-8 text-center">
              <XCircle className="mx-auto h-8 w-8 text-rose-400" />
              <h3 className="mt-3 text-[15px] font-semibold">Couldn't reach that site</h3>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                {result.error ?? "The site could not be fetched."} No data is shown rather than
                fabricated numbers.
              </p>
            </Panel>
          </Reveal>
        )
      ) : history && history.length > 0 ? (
        <div className="mt-8">
          <h2 className="mb-3 px-1 text-[15px] font-semibold">Recent audits</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {history.map((h) => (
              <Panel key={h.id} interactive className="p-4">
                <div className="flex items-center justify-between">
                  <span className="truncate text-[13px] font-medium">{h.url}</span>
                  <ScoreBadge score={h.scores?.overall ?? 0} />
                </div>
                <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <Clock className="h-3 w-3" /> {new Date(h.created_at).toLocaleDateString()}
                  <span>·</span>
                  {h.issue_count} issues
                </div>
              </Panel>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-8">
          <EmptyState
            icon={Search}
            title="Audit your first site"
            description="Enter a URL above to run a real technical SEO, performance-signal, security, and technology audit. Results are measured live and saved to history."
          />
        </div>
      )}
    </AppShell>
  );
}

function AuditReport({ analysis, scores }: { analysis: SeoAnalysis; scores: SeoScores }) {
  const issues = [...analysis.issues].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  return (
    <div className="mt-6 space-y-6">
      {/* Scores */}
      <Reveal>
        <Panel className="grid grid-cols-2 gap-4 p-6 sm:grid-cols-5">
          <ScoreGauge label="Overall" value={scores.overall} hero />
          <ScoreGauge label="Technical" value={scores.technical} />
          <ScoreGauge label="On-page" value={scores.on_page} />
          <ScoreGauge label="Content" value={scores.content} />
          <ScoreGauge label="Security" value={scores.security} />
        </Panel>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        {/* Issues */}
        <Reveal delay={80}>
          <section>
            <h3 className="mb-3 flex items-center gap-2 px-1 text-[15px] font-semibold">
              <AlertTriangle className="h-4 w-4 text-amber-300" /> Issues ({issues.length})
            </h3>
            {issues.length === 0 ? (
              <Panel className="flex items-center gap-3 p-6">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                <span className="text-sm">No technical issues detected on this page.</span>
              </Panel>
            ) : (
              <div className="space-y-2.5">
                {issues.map((iss, i) => (
                  <IssueCard key={i} issue={iss} />
                ))}
              </div>
            )}
          </section>
        </Reveal>

        {/* Facts + panels */}
        <div className="space-y-4">
          <Reveal delay={120}>
            <MetaPanel analysis={analysis} />
          </Reveal>
          <Reveal delay={160}>
            <TechPanel analysis={analysis} />
          </Reveal>
          <Reveal delay={200}>
            <SecurityPanel analysis={analysis} />
          </Reveal>
          <Reveal delay={240}>
            <SocialPanel analysis={analysis} />
          </Reveal>
          <Reveal delay={280}>
            <UnavailablePanel />
          </Reveal>
        </div>
      </div>
    </div>
  );
}

function IssueCard({ issue }: { issue: SeoIssue }) {
  const s = SEV_STYLE[issue.severity];
  return (
    <Panel className="p-4">
      <div className="flex items-start gap-3">
        <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", s.dot)} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={cn("text-[11px] font-semibold uppercase tracking-wide", s.text)}>
              {s.label}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">{issue.code}</span>
          </div>
          <p className="mt-1 text-[13.5px] leading-snug">{issue.message}</p>
          <p className="mt-1.5 flex items-start gap-1.5 text-[12px] text-muted-foreground">
            <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-fuchsia-300" />
            {issue.fix}
          </p>
        </div>
      </div>
    </Panel>
  );
}

function Fact({ label, value, ok }: { label: string; value: React.ReactNode; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn(
          "tabular font-medium",
          ok === true && "text-emerald-300",
          ok === false && "text-amber-300",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function MetaPanel({ analysis: a }: { analysis: SeoAnalysis }) {
  return (
    <Panel className="p-5">
      <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
        <Layers className="h-4 w-4 text-muted-foreground" /> On-page
      </h3>
      <div className="divide-y divide-[var(--hairline)]">
        <Fact
          label="Title"
          value={a.title ? `${a.title_length} chars` : "missing"}
          ok={!!a.title && a.title_length <= 65}
        />
        <Fact
          label="Meta description"
          value={a.meta_description ? `${a.meta_description_length} chars` : "missing"}
          ok={!!a.meta_description}
        />
        <Fact
          label="H1 count"
          value={a.heading_counts.h1 ?? 0}
          ok={(a.heading_counts.h1 ?? 0) === 1}
        />
        <Fact label="Canonical" value={a.canonical ? "present" : "missing"} ok={!!a.canonical} />
        <Fact label="Viewport" value={a.viewport ? "responsive" : "missing"} ok={!!a.viewport} />
        <Fact
          label="Structured data"
          value={a.has_json_ld ? a.schema_types.join(", ") || "yes" : "none"}
          ok={a.has_json_ld}
        />
        <Fact
          label="Images missing alt"
          value={`${a.images_missing_alt}/${a.image_count}`}
          ok={a.images_missing_alt === 0}
        />
        <Fact label="Word count" value={a.word_count} ok={a.word_count >= 200} />
        <Fact label="Links" value={`${a.internal_links} internal · ${a.external_links} external`} />
      </div>
    </Panel>
  );
}

function TechPanel({ analysis: a }: { analysis: SeoAnalysis }) {
  return (
    <Panel className="p-5">
      <h3 className="mb-3 flex items-center gap-2 text-[13px] font-semibold">
        <Code2 className="h-4 w-4 text-muted-foreground" /> Technology stack
      </h3>
      {a.technologies.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {a.technologies.map((t) => (
            <span
              key={t}
              className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] px-2.5 py-1 text-[12px]"
            >
              {t}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-muted-foreground">
          No technologies detected from page signatures.
        </p>
      )}
    </Panel>
  );
}

function SecurityPanel({ analysis: a }: { analysis: SeoAnalysis }) {
  const headers = Object.entries(a.security_headers);
  return (
    <Panel className="p-5">
      <h3 className="mb-3 flex items-center gap-2 text-[13px] font-semibold">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" /> Security
      </h3>
      <div className="mb-2">
        <Fact label="HTTPS" value={a.is_https ? "enabled" : "not enabled"} ok={a.is_https} />
      </div>
      <div className="grid grid-cols-1 gap-1.5">
        {headers.map(([h, present]) => (
          <div key={h} className="flex items-center gap-2 text-[12px]">
            {present ? (
              <Lock className="h-3 w-3 text-emerald-400" />
            ) : (
              <XCircle className="h-3 w-3 text-amber-400" />
            )}
            <span className={cn(present ? "text-foreground" : "text-muted-foreground")}>{h}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function SocialPanel({ analysis: a }: { analysis: SeoAnalysis }) {
  const socials = Object.entries(a.social_profiles);
  if (socials.length === 0) return null;
  return (
    <Panel className="p-5">
      <h3 className="mb-3 flex items-center gap-2 text-[13px] font-semibold">
        <Share2 className="h-4 w-4 text-muted-foreground" /> Social profiles
      </h3>
      <div className="flex flex-wrap gap-2">
        {socials.map(([name, href]) => (
          <a
            key={name}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] px-2.5 py-1 text-[12px] transition-colors hover:border-[color-mix(in_oklch,var(--primary)_35%,transparent)]"
          >
            <Link2 className="h-3 w-3" /> {name}
          </a>
        ))}
      </div>
    </Panel>
  );
}

function UnavailablePanel() {
  return (
    <Panel className="p-5">
      <div className="mb-2 flex items-center gap-2">
        <Image className="h-4 w-4 text-muted-foreground" aria-hidden />
        <h3 className="text-[13px] font-semibold">Requires a data provider</h3>
      </div>
      <p className="text-[12px] leading-relaxed text-muted-foreground">
        Keyword volumes, backlinks, and traffic estimates require a commercial SEO data provider
        (Semrush/Ahrefs-class). They're shown as{" "}
        <span className="text-foreground">unavailable</span> rather than invented. Connect a
        provider to populate them.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {["Keyword volume", "Backlinks", "Traffic estimate", "Domain authority"].map((t) => (
          <span
            key={t}
            className="rounded-lg border border-dashed border-[var(--hairline)] px-2.5 py-1 text-[11px] text-muted-foreground"
          >
            {t} · unavailable
          </span>
        ))}
      </div>
    </Panel>
  );
}

function ScoreGauge({ label, value, hero }: { label: string; value: number; hero?: boolean }) {
  const hue = value >= 80 ? 150 : value >= 50 ? 85 : 25;
  const color = `oklch(0.72 0.16 ${hue})`;
  const dim = hero ? 92 : 72;
  const track = hero ? 7 : 6;
  const r = (dim - track) / 2;
  const circ = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: dim, height: dim }}>
        <svg width={dim} height={dim} className="-rotate-90">
          <circle
            cx={dim / 2}
            cy={dim / 2}
            r={r}
            fill="none"
            stroke="color-mix(in oklch, currentColor 10%, transparent)"
            strokeWidth={track}
          />
          <circle
            cx={dim / 2}
            cy={dim / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={track}
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - value / 100)}
            style={{ transition: "stroke-dashoffset 0.9s cubic-bezier(0.16,1,0.3,1)" }}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span
            className={cn("tabular font-semibold", hero ? "text-2xl" : "text-lg")}
            style={{ color }}
          >
            {value}
          </span>
        </div>
      </div>
      <span
        className={cn(
          "mt-2 text-[11px] uppercase tracking-wide text-muted-foreground",
          hero && "font-semibold text-foreground",
        )}
      >
        {label}
      </span>
    </div>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const hue = score >= 80 ? 150 : score >= 50 ? 85 : 25;
  return (
    <span
      className="tabular rounded-md px-2 py-0.5 text-[12px] font-semibold"
      style={{ color: `oklch(0.75 0.16 ${hue})`, background: `oklch(0.72 0.16 ${hue} / 12%)` }}
    >
      {score}
    </span>
  );
}
