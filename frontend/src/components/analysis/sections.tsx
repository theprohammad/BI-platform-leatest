import { ResponsiveContainer, RadialBarChart, RadialBar, PolarAngleAxis } from "recharts";
import type {
  AnalysisData,
  CompetitorData,
  LeadData,
  MarketData,
  OpportunityData,
  OutreachData,
  PricingData,
  AuditData,
} from "@/services/api";
import {
  BadgeList,
  BulletList,
  EmptyState,
  InsightCard,
  PriorityBadge,
  SectionHeader,
  StatCard,
} from "./primitives";
import {
  LineChart as LineIcon,
  Swords,
  Users,
  Gauge,
  DollarSign,
  Sparkles,
  Send,
  Brain,
  ExternalLink,
} from "lucide-react";

// ---------------- Intelligence ----------------

export function IntelligenceSection({ data }: { data?: Record<string, unknown> }) {
  const entries = data ? Object.entries(data).filter(([, v]) => v != null && v !== "") : [];
  return (
    <section id="overview" className="scroll-mt-24">
      <SectionHeader
        icon={<Brain className="h-5 w-5" />}
        title="Shared Intelligence"
        description="Raw research summaries assembled by the intelligence pipeline before agent analysis."
      />
      {entries.length === 0 ? (
        <EmptyState title="No shared intelligence returned by the backend." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {entries.map(([key, value]) => (
            <InsightCard key={key} title={formatKey(key)}>
              <RenderValue value={value} />
            </InsightCard>
          ))}
        </div>
      )}
    </section>
  );
}

function formatKey(k: string) {
  return k.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function RenderValue({ value }: { value: unknown }) {
  if (value == null || value === "") return null;
  if (typeof value === "string" || typeof value === "number")
    return <p className="whitespace-pre-wrap text-sm">{String(value)}</p>;
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v === "string" || typeof v === "number")) {
      return <BulletList items={value.map(String)} />;
    }
    return (
      <div className="space-y-3">
        {value.map((v, i) => (
          <div key={i} className="rounded-lg border p-3 bg-muted/30">
            <RenderValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, v]) => v != null && v !== "",
    );
    if (entries.length === 0) return null;
    return (
      <div className="space-y-2">
        {entries.map(([k, v]) => (
          <div key={k}>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {formatKey(k)}
            </div>
            <div className="mt-1">
              <RenderValue value={v} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

// ---------------- Market ----------------

export function MarketSection({ data }: { data?: MarketData }) {
  if (!data) return null;
  const has =
    data.market_size ||
    data.growth_rate ||
    data.trends?.length ||
    data.opportunities?.length ||
    data.risks?.length ||
    data.recommended_services?.length;
  return (
    <section id="market" className="scroll-mt-24">
      <SectionHeader
        icon={<LineIcon className="h-5 w-5" />}
        title="Market Research"
        description="Market size, growth, trends, opportunities and risks."
      />
      {!has ? (
        <EmptyState title="No market data returned." />
      ) : (
        <div className="space-y-6">
          {(data.market_size || data.growth_rate) && (
            <div className="grid gap-4 sm:grid-cols-2">
              {data.market_size ? <StatCard label="Market Size" value={data.market_size} /> : null}
              {data.growth_rate ? <StatCard label="Growth Rate" value={data.growth_rate} /> : null}
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {data.trends?.length ? (
              <InsightCard title="Trends">
                <BadgeList items={data.trends} variant="info" />
              </InsightCard>
            ) : null}
            {data.opportunities?.length ? (
              <InsightCard title="Opportunities">
                <BulletList items={data.opportunities} />
              </InsightCard>
            ) : null}
            {data.risks?.length ? (
              <InsightCard title="Risks">
                <BadgeList items={data.risks} variant="danger" />
              </InsightCard>
            ) : null}
            {data.recommended_services?.length ? (
              <InsightCard title="Recommended Services">
                <BulletList items={data.recommended_services} />
              </InsightCard>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------- Competitors ----------------

export function CompetitorsSection({ data }: { data?: CompetitorData }) {
  if (!data) return null;
  return (
    <section id="competitors" className="scroll-mt-24">
      <SectionHeader
        icon={<Swords className="h-5 w-5" />}
        title="Competitor Analysis"
        description="Top competitors, gaps, pricing insights and strategic recommendations."
      />
      <div className="space-y-6">
        {data.top_competitors?.length ? (
          <div className="grid gap-4 md:grid-cols-2">
            {data.top_competitors.map((c, i) => (
              <InsightCard
                key={i}
                title={
                  <div className="flex items-center justify-between gap-2">
                    <span>{c.name || "Competitor"}</span>
                    {c.website ? (
                      <a
                        href={ensureHttp(c.website)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-medium text-fuchsia-300 hover:underline"
                      >
                        Visit <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                  </div>
                }
              >
                <div className="grid gap-3 sm:grid-cols-2">
                  {c.strengths?.length ? (
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-500 mb-1">
                        Strengths
                      </div>
                      <BulletList items={c.strengths} />
                    </div>
                  ) : null}
                  {c.weaknesses?.length ? (
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-500 mb-1">
                        Weaknesses
                      </div>
                      <BulletList items={c.weaknesses} />
                    </div>
                  ) : null}
                </div>
              </InsightCard>
            ))}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-3">
          {data.market_gap?.length ? (
            <InsightCard title="Market Gaps">
              <BulletList items={data.market_gap} />
            </InsightCard>
          ) : null}
          {data.pricing_insights?.length ? (
            <InsightCard title="Pricing Insights">
              <BulletList items={data.pricing_insights} />
            </InsightCard>
          ) : null}
          {data.recommendations?.length ? (
            <InsightCard title="Recommendations">
              <BulletList items={data.recommendations} />
            </InsightCard>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ensureHttp(u: string) {
  return /^https?:\/\//i.test(u) ? u : `https://${u}`;
}

// ---------------- Leads ----------------

export function LeadsSection({ data }: { data?: LeadData }) {
  if (!data) return null;
  const leads = data.qualified_leads ?? [];
  return (
    <section id="leads" className="scroll-mt-24">
      <SectionHeader
        icon={<Users className="h-5 w-5" />}
        title="Qualified Leads"
        description="Prospects most likely to buy, with pain points and recommended services."
      />
      {leads.length === 0 ? (
        <EmptyState title="No qualified leads returned." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {leads.map((l, i) => (
            <InsightCard
              key={i}
              title={
                <div className="flex items-center justify-between gap-2">
                  <span>{l.company || `Lead #${i + 1}`}</span>
                  <PriorityBadge priority={l.priority} />
                </div>
              }
            >
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  {l.industry ? <span>{l.industry}</span> : null}
                  {l.estimated_size ? <span>• {l.estimated_size}</span> : null}
                  {l.website ? (
                    <a
                      href={ensureHttp(l.website)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-fuchsia-300 hover:underline"
                    >
                      {l.website} <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
                </div>
                {l.why_good_fit ? <p className="text-sm">{l.why_good_fit}</p> : null}
                {l.pain_points?.length ? (
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                      Pain points
                    </div>
                    <BadgeList items={l.pain_points} variant="warning" />
                  </div>
                ) : null}
                {l.recommended_service ? (
                  <div className="rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)]/50 px-3 py-2 text-xs">
                    <span className="font-semibold">Recommended service: </span>
                    {l.recommended_service}
                  </div>
                ) : null}
              </div>
            </InsightCard>
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------- Audit ----------------

function ScoreRing({ label, value }: { label: string; value?: number }) {
  if (typeof value !== "number") return null;
  const clamped = Math.max(0, Math.min(100, value));
  const color = clamped >= 80 ? "#10b981" : clamped >= 50 ? "#f59e0b" : "#ef4444";
  const chartData = [{ name: label, value: clamped, fill: color }];
  return (
    <div className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/70 p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </p>
      </div>
      <div className="relative h-32">
        <ResponsiveContainer>
          <RadialBarChart
            innerRadius="70%"
            outerRadius="100%"
            data={chartData}
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar
              background={{ fill: "color-mix(in oklch, currentColor 8%, transparent)" }}
              dataKey="value"
              cornerRadius={12}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <span className="tabular text-[26px] font-semibold tracking-tight">{clamped}</span>
        </div>
      </div>
    </div>
  );
}

export function AuditSection({ data }: { data?: AuditData }) {
  if (!data) return null;
  return (
    <section id="audit" className="scroll-mt-24">
      <SectionHeader
        icon={<Gauge className="h-5 w-5" />}
        title="Website Audit"
        description="SEO, performance, UX and critical issues detected on the target website."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ScoreRing label="Overall" value={data.overall_score} />
        <ScoreRing label="SEO" value={data.seo_score} />
        <ScoreRing label="Performance" value={data.performance_score} />
        <ScoreRing label="UX" value={data.ux_score} />
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {data.strengths?.length ? (
          <InsightCard title="Strengths">
            <BadgeList items={data.strengths} variant="success" />
          </InsightCard>
        ) : null}
        {data.weaknesses?.length ? (
          <InsightCard title="Weaknesses">
            <BadgeList items={data.weaknesses} variant="warning" />
          </InsightCard>
        ) : null}
        {data.critical_issues?.length ? (
          <InsightCard title="Critical Issues">
            <BulletList items={data.critical_issues} />
          </InsightCard>
        ) : null}
        {data.recommendations?.length ? (
          <InsightCard title="Recommendations">
            <BulletList items={data.recommendations} />
          </InsightCard>
        ) : null}
        {data.recommended_services?.length ? (
          <InsightCard title="Recommended Services">
            <BadgeList items={data.recommended_services} variant="info" />
          </InsightCard>
        ) : null}
      </div>
    </section>
  );
}

// ---------------- Pricing ----------------

export function PricingSection({ data }: { data?: PricingData }) {
  if (!data) return null;
  return (
    <section id="pricing" className="scroll-mt-24">
      <SectionHeader
        icon={<DollarSign className="h-5 w-5" />}
        title="Pricing Intelligence"
        description="Competitor pricing models, gaps and recommended strategy."
      />
      {data.recommended_pricing_strategy ? (
        <InsightCard title="Recommended Pricing Strategy" className="mb-4">
          <p className="text-sm">{data.recommended_pricing_strategy}</p>
        </InsightCard>
      ) : null}
      {data.pricing_models?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {data.pricing_models.map((p, i) => (
            <InsightCard
              key={i}
              title={
                <div className="flex items-center justify-between gap-2">
                  <span>{p.company || `Model #${i + 1}`}</span>
                  {p.estimated_price ? (
                    <span className="text-xs font-semibold text-fuchsia-300">
                      {p.estimated_price}
                    </span>
                  ) : null}
                </div>
              }
            >
              {p.pricing_model ? <p className="text-sm mb-3">{p.pricing_model}</p> : null}
              <div className="grid gap-3 sm:grid-cols-2">
                {p.strengths?.length ? (
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-500 mb-1">
                      Strengths
                    </div>
                    <BulletList items={p.strengths} />
                  </div>
                ) : null}
                {p.weaknesses?.length ? (
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-500 mb-1">
                      Weaknesses
                    </div>
                    <BulletList items={p.weaknesses} />
                  </div>
                ) : null}
              </div>
            </InsightCard>
          ))}
        </div>
      ) : null}
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {data.pricing_gaps?.length ? (
          <InsightCard title="Pricing Gaps">
            <BulletList items={data.pricing_gaps} />
          </InsightCard>
        ) : null}
        {data.premium_services?.length ? (
          <InsightCard title="Premium Services">
            <BadgeList items={data.premium_services} variant="info" />
          </InsightCard>
        ) : null}
      </div>
    </section>
  );
}

// ---------------- Opportunity ----------------

export function OpportunitySection({ data }: { data?: OpportunityData }) {
  if (!data) return null;
  return (
    <section id="opportunity" className="scroll-mt-24">
      <SectionHeader
        icon={<Sparkles className="h-5 w-5" />}
        title="Growth Strategy"
        description="Executive opportunities, priority leads and next steps."
      />
      {data.business_summary ? (
        <div className="mb-6 rounded-2xl border border-[var(--hairline)] bg-gradient-to-br from-violet-500/10 to-fuchsia-500/[0.07] p-6">
          <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-fuchsia-300">
            Executive Summary
          </div>
          <p className="mt-2 text-sm leading-relaxed">{data.business_summary}</p>
          {data.estimated_project_value ? (
            <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-indigo-500/10 px-3 py-1 text-xs font-semibold text-fuchsia-300">
              Est. project value: {data.estimated_project_value}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        {data.top_opportunities?.length ? (
          <InsightCard title="Top Opportunities">
            <BulletList items={data.top_opportunities} />
          </InsightCard>
        ) : null}
        {data.best_target_industries?.length ? (
          <InsightCard title="Best Target Industries">
            <BadgeList items={data.best_target_industries} variant="info" />
          </InsightCard>
        ) : null}
        {data.competitive_advantages?.length ? (
          <InsightCard title="Competitive Advantages">
            <BulletList items={data.competitive_advantages} />
          </InsightCard>
        ) : null}
        {data.recommended_next_steps?.length ? (
          <InsightCard title="Recommended Next Steps">
            <BulletList items={data.recommended_next_steps} />
          </InsightCard>
        ) : null}
      </div>

      {data.highest_value_services?.length ? (
        <div className="mt-6">
          <h3 className="text-sm font-semibold mb-3">Highest Value Services</h3>
          <div className="grid gap-3 md:grid-cols-3">
            {data.highest_value_services.map((s, i) => (
              <div
                key={i}
                className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/70 p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-sm">{s.service || `Service #${i + 1}`}</div>
                  <PriorityBadge priority={s.demand} />
                </div>
                {s.reason ? <p className="mt-2 text-xs text-muted-foreground">{s.reason}</p> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {data.highest_priority_leads?.length ? (
        <div className="mt-6">
          <h3 className="text-sm font-semibold mb-3">Highest Priority Leads</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {data.highest_priority_leads.map((l, i) => (
              <div
                key={i}
                className="rounded-2xl border border-[var(--hairline)] bg-[var(--surface)]/70 p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-sm">{l.company || `Lead #${i + 1}`}</div>
                  <PriorityBadge priority={l.priority} />
                </div>
                {l.reason ? <p className="mt-2 text-xs text-muted-foreground">{l.reason}</p> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------- Outreach ----------------

export function OutreachSection({ data }: { data?: OutreachData }) {
  if (!data) return null;
  return (
    <section id="outreach" className="scroll-mt-24">
      <SectionHeader
        icon={<Send className="h-5 w-5" />}
        title="Outreach Kit"
        description="Ready-to-send emails, LinkedIn messages and a cold call script."
      />

      {data.emails?.length ? (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold">Emails</h3>
          <div className="grid gap-4 md:grid-cols-2">
            {data.emails.map((e, i) => (
              <InsightCard
                key={i}
                title={
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">To: {e.company || "—"}</span>
                    <CopyButton text={`Subject: ${e.subject ?? ""}\n\n${e.body ?? ""}`} />
                  </div>
                }
              >
                {e.subject ? <div className="mb-2 text-sm font-semibold">{e.subject}</div> : null}
                {e.body ? (
                  <pre className="whitespace-pre-wrap font-sans text-sm text-foreground/90">
                    {e.body}
                  </pre>
                ) : null}
              </InsightCard>
            ))}
          </div>
        </div>
      ) : null}

      {data.linkedin_messages?.length ? (
        <div className="mt-8 space-y-4">
          <h3 className="text-sm font-semibold">LinkedIn Messages</h3>
          <div className="grid gap-4 md:grid-cols-2">
            {data.linkedin_messages.map((m, i) => (
              <InsightCard
                key={i}
                title={
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">To: {m.company || "—"}</span>
                    <CopyButton text={m.message ?? ""} />
                  </div>
                }
              >
                {m.message ? <p className="whitespace-pre-wrap text-sm">{m.message}</p> : null}
              </InsightCard>
            ))}
          </div>
        </div>
      ) : null}

      {data.cold_call_script ? (
        <div className="mt-8">
          <InsightCard
            title={
              <div className="flex items-center justify-between gap-2">
                <span>Cold Call Script</span>
                <CopyButton text={data.cold_call_script} />
              </div>
            }
          >
            <pre className="whitespace-pre-wrap font-sans text-sm">{data.cold_call_script}</pre>
          </InsightCard>
        </div>
      ) : null}
    </section>
  );
}

function CopyButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => {
        if (typeof navigator !== "undefined" && navigator.clipboard) {
          navigator.clipboard.writeText(text);
        }
      }}
      className="text-[11px] font-medium text-fuchsia-300 hover:underline"
    >
      Copy
    </button>
  );
}

// ---------------- Overview stats ----------------

export function OverviewStats({ data }: { data: AnalysisData }) {
  const leadsCount = data.leads?.qualified_leads?.length ?? 0;
  const competitorsCount = data.competitors?.top_competitors?.length ?? 0;
  const opportunitiesCount = data.opportunity?.top_opportunities?.length ?? 0;
  const overall = data.audit?.overall_score;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label="Qualified Leads" value={leadsCount} icon={<Users className="h-4 w-4" />} />
      <StatCard
        label="Top Competitors"
        value={competitorsCount}
        icon={<Swords className="h-4 w-4" />}
      />
      <StatCard
        label="Opportunities"
        value={opportunitiesCount}
        icon={<Sparkles className="h-4 w-4" />}
      />
      <StatCard
        label="Audit Score"
        value={typeof overall === "number" ? `${overall}/100` : "—"}
        icon={<Gauge className="h-4 w-4" />}
      />
    </div>
  );
}
