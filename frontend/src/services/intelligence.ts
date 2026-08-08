/**
 * v2 Intelligence OS client — conversational intake, SSE research narrative,
 * twin workspace, cited analyst chat. Mirrors backend /v2 (stable interface).
 */
import axios from "axios";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

const client = axios.create({ baseURL: BASE_URL, timeout: 60_000 });

/* ---------- types (mirror app/graph/ontology.py — stable) ---------------- */

export interface TrustVector {
  confidence: number;
  source_quality: number;
  evidence_count: number;
  freshness: number;
  corroboration: number;
  reasoning_quality: number | null;
}

export interface GraphClaim {
  id: string;
  kind: "fact" | "event" | "metric";
  statement: string;
  value: string | null;
  value_entity_id?: string | null;
  predicate?: string | null;
  topic: string;
  as_of: string | null;
  status?: "active" | "unsupported" | "superseded";
  superseded_by?: string | null;
  evidence_ids: string[];
  trust: TrustVector;
  created_at: string;
}

export interface GraphInsight {
  id: string;
  kind: string;
  title: string;
  body: string;
  /** Reviewer rationale, split out server-side so it is never shown inline. */
  validation_note?: string;
  claim_ids: string[];
  trust: TrustVector;
  authored_by: string;
  debate_status: string;
}

export interface EvidenceSummary {
  id: string;
  url: string;
  domain: string;
  title: string;
  published_date: string | null;
  retrieved_at: string;
  quality_score: number;
  preview: string;
}

export interface TwinView {
  organization: { id: string; name: string; website: string | null; industry: string | null };
  root_entity_id: string;
  coverage: Record<string, { claims: number; newest: string }>;
  profile_claims: GraphClaim[];
  timeline: GraphClaim[];
  insights: GraphInsight[];
}

export interface AnalyzeStarted {
  status: "started";
  run_id: string;
  organization_id: string;
  root_entity_id: string;
  brief: {
    organization: string;
    industry: string | null;
    location: string | null;
    objectives: string[];
  };
}

export interface AnalyzeClarify {
  status: "needs_clarification";
  question: string;
}

export interface RunEvent {
  type: string;
  run_id: string;
  payload: Record<string, unknown>;
  at: string;
}

export interface Citation {
  claim_id: string;
  statement: string;
  trust: TrustVector;
  evidence: { url: string; title: string }[];
}

export interface ChatAnswer {
  answer: string;
  citations: Citation[];
  needs_research: boolean;
  proposed_research: string | null;
}

/* ---------- calls --------------------------------------------------------- */

export async function startAnalysis(
  message: string,
  priorMessage?: string,
): Promise<AnalyzeStarted | AnalyzeClarify> {
  const { data } = await client.post("/v2/analyze", {
    message,
    prior_message: priorMessage ?? null,
  });
  return data;
}

export function streamRunEvents(
  runId: string,
  onEvent: (e: RunEvent) => void,
  onDone: (failed: boolean) => void,
): () => void {
  const source = new EventSource(`${BASE_URL}/v2/runs/${runId}/events`);
  source.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as RunEvent;
      onEvent(event);
      if (event.type === "run.completed" || event.type === "run.failed") {
        source.close();
        onDone(event.type === "run.failed");
      }
    } catch {
      /* keepalive */
    }
  };
  source.onerror = () => {
    source.close();
    onDone(true);
  };
  return () => source.close();
}

export async function fetchTwins() {
  const { data } = await client.get("/v2/twins");
  return data as { id: string; name: string; website: string | null; industry: string | null }[];
}

export async function fetchTwin(orgId: string): Promise<TwinView> {
  const { data } = await client.get(`/v2/twins/${orgId}`);
  return data;
}

export async function fetchTwinEvidence(orgId: string): Promise<EvidenceSummary[]> {
  const { data } = await client.get(`/v2/twins/${orgId}/evidence`);
  return data;
}

export async function askAnalyst(orgId: string, message: string): Promise<ChatAnswer> {
  const { data } = await client.post(`/v2/twins/${orgId}/chat`, { message }, { timeout: 120_000 });
  return data;
}

/* ==========================================================================
 * Intelligence Workspace — product read surface (backend /v2, read-only).
 * ======================================================================== */

export interface Organization {
  id: string;
  name: string;
  website: string | null;
  industry: string | null;
  created_at: string;
}

export interface PlaybookMeta {
  id: string;
  version: string;
  description: string;
  specialists: string[];
}

export interface RunSummary {
  run_id: string;
  organization_id: string | null;
  status: string;
  created_at: string;
  brief: Record<string, unknown>;
  playbook: { id: string; version: string } | null;
  summary: Record<string, number>;
}

export interface DashboardView {
  organization: { id: string; name: string; root_entity_id: string | null };
  validated_insights: GraphInsight[];
  other_insights: GraphInsight[];
  recommendations: GraphInsight[];
  disputes: { open: GraphInsight[]; deferred: GraphInsight[]; resolved: GraphInsight[] };
  research_history: RunSummary[];
  counts: {
    validated: number;
    recommendations: number;
    disputes_open: number;
    disputes_deferred: number;
    disputes_resolved: number;
    runs: number;
  };
}

export interface ClaimEvidenceBlock {
  claim: GraphClaim;
  evidence: EvidenceSummary[];
}

export interface RecommendationChain {
  recommendation: GraphInsight;
  supporting_insights: GraphInsight[];
  claims: ClaimEvidenceBlock[];
}

export interface TimelineEntry {
  from: string | null;
  to: string;
  reason: string;
  counterpart: string | null;
  run_id: string | null;
  at: string;
}

export interface ClaimTimeline {
  claim: GraphClaim;
  timeline: TimelineEntry[];
}

export interface DisputeDetail {
  dispute: GraphInsight;
  sides: ClaimEvidenceBlock[];
  status: string;
  winner_claim_id: string | null;
}

export interface SearchResults {
  entities: { id: string; name: string; type: string; aliases: string[] }[];
  claims: GraphClaim[];
  insights: GraphInsight[];
  recommendations: GraphInsight[];
  /* Cross-module results (Phase 2 breadth). Optional so older callers keep working. */
  competitors?: { id: string; name: string }[];
  monitoring?: {
    id: string;
    competitor: string;
    category: string;
    severity: string;
    summary: string;
    detected_at: string;
  }[];
  leads?: {
    id: string;
    company: string;
    domain: string | null;
    stage: string;
    score: number;
    score_band: string;
  }[];
  website_audits?: {
    id: string;
    url: string;
    ok: boolean;
    overall_score: number | null;
    created_at: string;
  }[];
  organization_scoped?: boolean;
}

/** Server-side export URLs. Returned as links so the browser handles download. */
export function reportPdfUrl(organizationId: string, kind: string): string {
  return `${BASE_URL}/v2/exports/report.pdf?organization_id=${encodeURIComponent(
    organizationId,
  )}&kind=${encodeURIComponent(kind)}`;
}

export function datasetCsvUrl(organizationId: string, dataset: string): string {
  return `${BASE_URL}/v2/exports/${encodeURIComponent(
    dataset,
  )}.csv?organization_id=${encodeURIComponent(organizationId)}`;
}

export interface ChangeReport {
  since: string;
  new_claims: number;
  new_events: unknown[];
  supersessions: {
    predicate: string;
    old_value: string;
    new_value: string;
    old_claim: string;
    new_claim: string;
  }[];
  disputes_opened: unknown[];
  signals: unknown[];
}

export async function fetchOrganizations(): Promise<Organization[]> {
  const { data } = await client.get("/v2/organizations");
  return data;
}

export async function fetchPlaybooks(): Promise<PlaybookMeta[]> {
  const { data } = await client.get("/v2/playbooks");
  return data;
}

export async function fetchDashboard(
  orgId: string,
  filters?: { status?: string; playbook?: string; since?: string },
): Promise<DashboardView> {
  const { data } = await client.get(`/v2/twins/${orgId}/dashboard`, {
    params: filters,
  });
  return data;
}

export async function fetchRecommendationChain(
  orgId: string,
  insightId: string,
): Promise<RecommendationChain> {
  const { data } = await client.get(`/v2/twins/${orgId}/recommendations/${insightId}/chain`);
  return data;
}

export async function fetchClaimTimeline(claimId: string): Promise<ClaimTimeline> {
  const { data } = await client.get(`/v2/claims/${claimId}/timeline`);
  return data;
}

export async function fetchDisputes(orgId: string): Promise<GraphInsight[]> {
  const { data } = await client.get(`/v2/twins/${orgId}/disputes`);
  return data;
}

export async function fetchDisputeDetail(orgId: string, insightId: string): Promise<DisputeDetail> {
  const { data } = await client.get(`/v2/twins/${orgId}/disputes/${insightId}`);
  return data;
}

export async function searchWorkspace(q: string, orgId?: string): Promise<SearchResults> {
  const { data } = await client.get("/v2/search", {
    params: { q, org_id: orgId },
  });
  return data;
}

export async function startAnalysisWithPlaybook(
  message: string,
  playbook?: string,
  priorMessage?: string,
): Promise<AnalyzeStarted | AnalyzeClarify> {
  const { data } = await client.post("/v2/analyze", {
    message,
    playbook: playbook ?? null,
    prior_message: priorMessage ?? null,
  });
  return data;
}

export async function refreshTwin(
  orgId: string,
): Promise<{ status: string; run_id: string; organization_id: string }> {
  const { data } = await client.post(`/v2/twins/${orgId}/refresh`);
  return data;
}

export async function fetchChanges(orgId: string, since: string): Promise<ChangeReport> {
  const { data } = await client.get(`/v2/twins/${orgId}/changes`, {
    params: { since },
  });
  return data;
}

/* ==========================================================================
 * Executive Briefing — workspace-level morning brief (read-only, additive).
 * ======================================================================== */

export interface BriefingTwin {
  id: string;
  name: string;
  counts: {
    validated: number;
    recommendations: number;
    disputes_open: number;
    signals: number;
    runs: number;
  };
  last_run: string | null;
}

export interface PriorityItem {
  severity: "urgent" | "high" | "medium" | "low";
  kind: "dispute" | "signal" | "recommendation";
  org_id: string;
  org_name: string;
  id: string;
  title: string;
  confidence: number;
  at: string | null;
  evidence_count: number;
  action: string;
}

export interface Discovery {
  org_id: string;
  org_name: string;
  id: string;
  kind: string;
  title: string;
  confidence: number;
  at: string | null;
  status: string;
}

export interface ExecutiveBriefing {
  generated_at: string;
  twins: BriefingTwin[];
  totals: {
    validated: number;
    recommendations: number;
    disputes_open: number;
    signals: number;
    runs: number;
    evidence: number;
  };
  priority_feed: PriorityItem[];
  discoveries: Discovery[];
  has_data: boolean;
}

export async function fetchBriefing(): Promise<ExecutiveBriefing> {
  const { data } = await client.get("/v2/briefing");
  return data;
}

/* ==========================================================================
 * Competitor Intelligence — sourced from the graph (read-only, additive).
 * ======================================================================== */

export interface CompetitorClaim {
  id: string;
  statement: string;
  predicate: string | null;
  value: string | null;
  confidence: number;
  evidence_count: number;
  as_of: string | null;
}

export interface Competitor {
  id: string;
  name: string;
  aliases: string[];
  claim_count: number;
  evidence_count: number;
  confidence: number | null;
  profile: Record<string, CompetitorClaim[]>;
  edge_confidence: number | null;
}

export interface CompetitorsView {
  organization: { id: string; name: string };
  competitors: Competitor[];
  has_data: boolean;
}

export async function fetchCompetitors(orgId: string): Promise<CompetitorsView> {
  const { data } = await client.get(`/v2/twins/${orgId}/competitors`);
  return data;
}

/* ==========================================================================
 * SEO / Website Intelligence module (Semrush-class) — all real measured data.
 * ======================================================================== */

export interface SeoIssue {
  severity: "high" | "medium" | "low";
  code: string;
  message: string;
  fix: string;
}

export interface SeoAnalysis {
  url: string;
  final_url: string;
  status_code: number | null;
  title: string;
  title_length: number;
  meta_description: string;
  meta_description_length: number;
  canonical: string | null;
  robots_meta: string | null;
  lang: string | null;
  viewport: string | null;
  h1: string[];
  heading_counts: Record<string, number>;
  open_graph: Record<string, string>;
  twitter_card: Record<string, string>;
  schema_types: string[];
  has_json_ld: boolean;
  image_count: number;
  images_missing_alt: number;
  internal_links: number;
  external_links: number;
  nofollow_links: number;
  social_profiles: Record<string, string>;
  word_count: number;
  technologies: string[];
  security_headers: Record<string, boolean>;
  is_https: boolean;
  issues: SeoIssue[];
}

export interface SeoScores {
  technical: number;
  on_page: number;
  content: number;
  security: number;
  overall: number;
}

export interface SeoAuditResult {
  ok: boolean;
  audit_id?: string;
  analysis?: SeoAnalysis;
  scores?: SeoScores;
  error?: string;
  detail?: string;
  fetched_at: string;
}

export interface AuditHistoryItem {
  id: string;
  url: string;
  ok: boolean;
  scores: SeoScores;
  issue_count: number;
  created_at: string;
}

export async function runWebsiteAudit(
  url: string,
  organizationId?: string,
): Promise<SeoAuditResult> {
  const { data } = await client.post("/v2/tools/website-audit", {
    url,
    organization_id: organizationId ?? null,
  });
  return data;
}

export async function fetchAuditHistory(params?: {
  organizationId?: string;
  url?: string;
}): Promise<AuditHistoryItem[]> {
  const { data } = await client.get("/v2/website-audits", {
    params: { organization_id: params?.organizationId, url: params?.url },
  });
  return data.audits;
}

export async function fetchAuditDetail(
  auditId: string,
): Promise<SeoAuditResult & { analysis: SeoAnalysis }> {
  const { data } = await client.get(`/v2/website-audits/${auditId}`);
  return data;
}

/* ==========================================================================
 * Competitor Monitoring module (Crayon-class) — real change detection.
 * ======================================================================== */

export interface CompetitorChange {
  id: string;
  competitor_name: string;
  url: string;
  category: "messaging" | "pricing" | "tech" | "content" | "feature" | "release";
  severity: "critical" | "high" | "medium" | "low";
  summary: string;
  before: string | null;
  after: string | null;
  acknowledged: boolean;
  detected_at: string;
}

export interface MonitorResult {
  ok: boolean;
  is_first?: boolean;
  changes: Array<
    Omit<CompetitorChange, "id" | "competitor_name" | "url" | "acknowledged" | "detected_at">
  >;
  error?: string;
}

export interface CompetitorReport {
  organization_id: string;
  total_changes: number;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
  most_active: Array<{ competitor: string; changes: number }>;
  recent: CompetitorChange[];
  has_data: boolean;
}

export async function monitorCompetitor(input: {
  organizationId: string;
  competitorName: string;
  url: string;
  pageType?: string;
}): Promise<MonitorResult> {
  const { data } = await client.post("/v2/competitors/monitor", {
    organization_id: input.organizationId,
    competitor_name: input.competitorName,
    url: input.url,
    page_type: input.pageType ?? "homepage",
  });
  return data;
}

export async function fetchCompetitorTimeline(
  organizationId: string,
  competitorName?: string,
): Promise<CompetitorChange[]> {
  const { data } = await client.get("/v2/competitors/timeline", {
    params: { organization_id: organizationId, competitor_name: competitorName },
  });
  return data.changes;
}

export async function fetchCompetitorAlerts(organizationId: string): Promise<CompetitorChange[]> {
  const { data } = await client.get("/v2/competitors/alerts", {
    params: { organization_id: organizationId },
  });
  return data.alerts;
}

export async function acknowledgeChange(changeId: string): Promise<void> {
  await client.post(`/v2/competitors/changes/${changeId}/acknowledge`);
}

export async function fetchCompetitorReport(organizationId: string): Promise<CompetitorReport> {
  const { data } = await client.get("/v2/competitors/report", {
    params: { organization_id: organizationId },
  });
  return data;
}

/* ==========================================================================
 * Sales Intelligence module (Apollo-class) — real enrichment + CRM + outreach.
 * ======================================================================== */

export interface LeadSummary {
  id: string;
  company_name: string;
  domain: string | null;
  industry: string | null;
  location: string | null;
  employee_range: string | null;
  score: number;
  score_band: "priority" | "hot" | "warm" | "cold";
  stage: string;
  created_at: string;
}

export interface ScoreFactor {
  name: string;
  points: number;
  max_points: number;
  detail: string;
}

export interface LeadContact {
  id: string;
  name: string;
  title: string | null;
  department: string | null;
  email: string | null;
  email_status: "found" | "not_found";
  linkedin: string | null;
  source: string | null;
}

export interface LeadDetail extends LeadSummary {
  enrichment: Record<string, unknown>;
  score_breakdown: { score: number; band: string; confidence: number; factors: ScoreFactor[] };
  contacts: LeadContact[];
  notes: Array<{ id: string; body: string; author: string; created_at: string }>;
  tasks: Array<{
    id: string;
    title: string;
    due_date: string | null;
    done: boolean;
    created_at: string;
  }>;
  activities: Array<{ id: string; kind: string; summary: string; created_at: string }>;
}

export interface PipelineReport {
  total_leads: number;
  by_stage: Record<string, number>;
  by_band: Record<string, number>;
  conversion_rate: number;
  contact_rate: number;
  avg_score: number;
  has_data: boolean;
}

export interface GeneratedEmail {
  subject: string;
  body: string;
  personalization_notes: string[];
  kind: string;
  grounded_facts: Record<string, unknown>;
}

export const PIPELINE_STAGES = [
  "discovered",
  "qualified",
  "contacted",
  "meeting",
  "proposal",
  "won",
  "lost",
] as const;

export async function discoverLead(input: {
  companyName: string;
  domain: string;
  industry?: string;
  location?: string;
  employeeRange?: string;
  icpIndustry?: string;
  icpEmployeeRange?: string;
}): Promise<{
  lead_id: string;
  score: number;
  band: string;
  contacts_found: number;
  enrichment_ok: boolean;
}> {
  const { data } = await client.post("/v2/sales/discover", {
    company_name: input.companyName,
    domain: input.domain,
    industry: input.industry,
    location: input.location,
    employee_range: input.employeeRange,
    icp_industry: input.icpIndustry,
    icp_employee_range: input.icpEmployeeRange,
  });
  return data;
}

export async function fetchLeads(filters?: {
  stage?: string;
  band?: string;
  industry?: string;
  minScore?: number;
}): Promise<LeadSummary[]> {
  const { data } = await client.get("/v2/sales/leads", {
    params: {
      stage: filters?.stage,
      band: filters?.band,
      industry: filters?.industry,
      min_score: filters?.minScore,
    },
  });
  return data.leads;
}

export async function fetchLeadDetail(leadId: string): Promise<LeadDetail> {
  const { data } = await client.get(`/v2/sales/leads/${leadId}`);
  return data;
}

export async function moveLeadStage(leadId: string, stage: string): Promise<void> {
  await client.post(`/v2/sales/leads/${leadId}/stage`, { stage });
}

export async function addLeadNote(leadId: string, body: string): Promise<void> {
  await client.post(`/v2/sales/leads/${leadId}/notes`, { body });
}

export async function addLeadTask(leadId: string, title: string, dueDate?: string): Promise<void> {
  await client.post(`/v2/sales/leads/${leadId}/tasks`, { title, due_date: dueDate });
}

export async function completeLeadTask(taskId: string): Promise<void> {
  await client.post(`/v2/sales/tasks/${taskId}/complete`);
}

export async function generateEmail(
  leadId: string,
  kind = "cold",
  includeCompetitorContext = false,
): Promise<{ ok: boolean; email?: GeneratedEmail; error?: string }> {
  const { data } = await client.post(`/v2/sales/leads/${leadId}/email`, {
    kind,
    include_competitor_context: includeCompetitorContext,
  });
  return data;
}

export async function fetchPipeline(): Promise<PipelineReport> {
  const { data } = await client.get("/v2/sales/pipeline");
  return data;
}

/* Monitoring status (baseline / stable / changes) per watched URL. */
export interface WatchedUrl {
  url: string;
  competitor_name: string;
  snapshot_count: number;
  first_scan: string | null;
  last_scan: string | null;
  change_count: number;
  status: "baseline" | "stable" | "changes_detected";
}
export interface MonitoringStatus {
  watched: WatchedUrl[];
  total_snapshots: number;
  watched_count: number;
}
export async function fetchMonitoringStatus(organizationId: string): Promise<MonitoringStatus> {
  const { data } = await client.get("/v2/competitors/status", {
    params: { organization_id: organizationId },
  });
  return data;
}

/* ==========================================================================
 * Finding detail — executive source transparency for a single finding.
 * ======================================================================== */

export interface FindingSource {
  id: string;
  url: string;
  domain: string;
  title: string;
  source_type: string;
  authentication_score: number;
  reliability_stars: number;
  extracted_at: string;
  preview: string;
}

export interface FindingDetail {
  id: string;
  statement: string;
  topic: string;
  confidence: number;
  corroboration: number;
  source_quality: number;
  freshness: number;
  status: string;
  as_of: string | null;
  created_at: string;
  sources: FindingSource[];
  source_count: number;
  used_by: {
    recommendations: Array<{ id: string; title: string; confidence: number }>;
    insights: Array<{ id: string; title: string; confidence: number }>;
  };
}

export async function fetchFindingDetail(findingId: string): Promise<FindingDetail> {
  const { data } = await client.get(`/v2/findings/${findingId}`);
  return data;
}

/* ==========================================================================
 * Run status — used as a safety net so analysis completion is deterministic
 * even if the live event stream drops before emitting a terminal event.
 * ======================================================================== */

export interface RunStatus {
  run_id: string;
  status: string; // running | completed | failed
  organization_id?: string | null;
}

export async function fetchRunStatus(runId: string): Promise<RunStatus> {
  const { data } = await client.get(`/v2/runs/${runId}`);
  return data;
}

/** Poll until the run reaches a terminal state. Resolves true if it failed. */
export async function waitForRunCompletion(
  runId: string,
  { intervalMs = 2000, timeoutMs = 15 * 60_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<{ failed: boolean; timedOut: boolean }> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const s = await fetchRunStatus(runId);
      if (s.status === "completed") return { failed: false, timedOut: false };
      if (s.status === "failed") return { failed: true, timedOut: false };
    } catch {
      /* transient — keep polling */
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { failed: false, timedOut: true };
}

/* ==========================================================================
 * Phase 1 — Mission Control alerts, monitoring activity, cross-linking.
 * ======================================================================== */

export interface CriticalAlert {
  kind: "conflict" | "competitor_change" | "website_health";
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  at: string | null;
  action: string;
  ref: { type: string; id: string };
}

export async function fetchAlerts(
  orgId: string,
): Promise<{ alerts: CriticalAlert[]; count: number }> {
  const { data } = await client.get(`/v2/twins/${orgId}/alerts`);
  return data;
}

export interface MonitoringEvent {
  kind: "baseline_created" | "scan_completed" | "change_detected";
  competitor_name: string;
  url: string;
  at: string;
  detail: string;
  severity?: string;
  category?: string;
  change_id?: string;
}

export async function fetchMonitoringActivity(
  organizationId: string,
): Promise<{ events: MonitoringEvent[] }> {
  const { data } = await client.get("/v2/competitors/activity", {
    params: { organization_id: organizationId },
  });
  return data;
}

export interface RelatedIntelligence {
  finding_id: string;
  related_findings: Array<{ id: string; statement: string; confidence: number; topic: string }>;
  competitors: Array<{ id: string; name: string }>;
  recommendations: Array<{ id: string; title: string; confidence: number }>;
}

export async function fetchFindingRelated(findingId: string): Promise<RelatedIntelligence> {
  const { data } = await client.get(`/v2/findings/${findingId}/related`);
  return data;
}

/* ==========================================================================
 * Opportunity lifecycle — the decision overlay on derived opportunities.
 * ======================================================================== */

export type OpportunityStatus = "new" | "reviewing" | "in_progress" | "completed" | "dismissed";

export interface OpportunityStateMap {
  states: Record<string, { status: OpportunityStatus; owner: string | null; updated_at: string }>;
  valid_statuses: OpportunityStatus[];
}

export async function fetchOpportunityStates(orgId: string): Promise<OpportunityStateMap> {
  const { data } = await client.get(`/v2/twins/${orgId}/opportunity-states`);
  return data;
}

export async function setOpportunityState(
  orgId: string,
  payload: { opportunity_key: string; status?: OpportunityStatus; owner?: string },
): Promise<{ opportunity_key: string; status: string; owner: string | null }> {
  const { data } = await client.post(`/v2/twins/${orgId}/opportunity-states`, payload);
  return data;
}
