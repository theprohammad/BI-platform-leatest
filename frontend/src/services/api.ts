import axios, { AxiosError } from "axios";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  // Analysis pipeline runs multiple LLM calls — allow generous timeout.
  timeout: 300_000,
});

// ---- Contract types (mirror backend/app/schemas + prompts) --------------

export interface AnalysisRequest {
  company_name: string;
  website: string;
  industry: string;
  target_market: string;
}

export interface AnalysisResponse<T = AnalysisData> {
  success: boolean;
  message: string;
  data: T;
}

// Agent outputs are LLM-produced JSON matching prompts in
// backend/app/utils/prompts.py. Fields may be absent — always use optional
// chaining and hide sections when missing.

export interface MarketData {
  market_size?: string;
  growth_rate?: string;
  trends?: string[];
  opportunities?: string[];
  risks?: string[];
  recommended_services?: string[];
}

export interface Competitor {
  name?: string;
  website?: string;
  strengths?: string[];
  weaknesses?: string[];
}

export interface CompetitorData {
  top_competitors?: Competitor[];
  market_gap?: string[];
  pricing_insights?: string[];
  recommendations?: string[];
}

export interface QualifiedLead {
  company?: string;
  website?: string;
  industry?: string;
  estimated_size?: string;
  why_good_fit?: string;
  pain_points?: string[];
  recommended_service?: string;
  priority?: "High" | "Medium" | "Low" | string;
}

export interface LeadData {
  qualified_leads?: QualifiedLead[];
}

export interface PricingModel {
  company?: string;
  pricing_model?: string;
  estimated_price?: string;
  strengths?: string[];
  weaknesses?: string[];
}

export interface PricingData {
  pricing_models?: PricingModel[];
  pricing_gaps?: string[];
  recommended_pricing_strategy?: string;
  premium_services?: string[];
}

export interface AuditData {
  overall_score?: number;
  seo_score?: number;
  performance_score?: number;
  ux_score?: number;
  strengths?: string[];
  weaknesses?: string[];
  critical_issues?: string[];
  recommendations?: string[];
  recommended_services?: string[];
}

export interface HighestValueService {
  service?: string;
  reason?: string;
  demand?: "High" | "Medium" | "Low" | string;
}

export interface PriorityLead {
  company?: string;
  reason?: string;
  priority?: "High" | "Medium" | "Low" | string;
}

export interface OpportunityData {
  business_summary?: string;
  top_opportunities?: string[];
  best_target_industries?: string[];
  highest_value_services?: HighestValueService[];
  competitive_advantages?: string[];
  highest_priority_leads?: PriorityLead[];
  estimated_project_value?: string;
  recommended_next_steps?: string[];
}

export interface OutreachEmail {
  company?: string;
  subject?: string;
  body?: string;
}

export interface LinkedInMessage {
  company?: string;
  message?: string;
}

export interface OutreachData {
  emails?: OutreachEmail[];
  linkedin_messages?: LinkedInMessage[];
  cold_call_script?: string;
}

export interface AnalysisData {
  intelligence?: Record<string, unknown>;
  market?: MarketData;
  competitors?: CompetitorData;
  leads?: LeadData;
  audit?: AuditData;
  pricing?: PricingData;
  opportunity?: OpportunityData;
  outreach?: OutreachData;
}

// ---- API calls ----------------------------------------------------------

export async function runAnalysis(
  payload: AnalysisRequest,
): Promise<AnalysisResponse> {
  const res = await apiClient.post<AnalysisResponse>("/analyze", payload);
  return res.data;
}

export async function healthCheck(): Promise<{ status: string }> {
  const res = await apiClient.get<{ status: string }>("/health");
  return res.data;
}

// ---- Error helpers ------------------------------------------------------

export function extractApiError(err: unknown): string {
  if (err instanceof AxiosError) {
    const status = err.response?.status;
    const data = err.response?.data as
      | { detail?: unknown; message?: string }
      | undefined;

    if (status === 422 && Array.isArray(data?.detail)) {
      return data!.detail
        .map((d: { loc?: unknown[]; msg?: string }) =>
          `${(d.loc ?? []).join(".")}: ${d.msg ?? ""}`.trim(),
        )
        .join("; ");
    }
    if (typeof data?.detail === "string") return data.detail;
    if (data?.message) return data.message;

    if (status === 400) return "Bad request. Please check your input.";
    if (status === 401) return "Unauthorized.";
    if (status === 403) return "Forbidden.";
    if (status === 404) return "Endpoint not found.";
    if (status === 500) return "The backend encountered an internal error.";
    if (err.code === "ECONNABORTED") return "Request timed out.";
    if (err.code === "ERR_NETWORK")
      return "Unable to reach the backend. Verify VITE_API_BASE_URL and CORS.";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Unknown error";
}
