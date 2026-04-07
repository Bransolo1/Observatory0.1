const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_V1 = `${API_BASE}/api/v1`;

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("observatory_token") : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_V1}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  return res.json();
}

// --- Auth ---
export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  org_id: string | null;
  role: string | null;
}

export interface UserResponse {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
}

export interface OrgOption {
  id: string;
  name: string;
  slug: string;
  role: string;
  is_onboarded: boolean;
}

export interface OnboardingState {
  is_onboarded: boolean;
  onboarding_step: number;
  product_description: string | null;
  lens_weights: Record<string, number>;
  product_areas_count: number;
  competitors_count: number;
  data_sources_count: number;
}

export interface ProductArea {
  id: string;
  name: string;
  description: string | null;
}

export interface DataSource {
  id: string;
  source_type: string;
  name: string;
  status: string;
}

export const onboarding = {
  get: (orgId: string) => request<OnboardingState>(`/orgs/${orgId}/onboarding`),
  update: (orgId: string, data: { step?: number; product_description?: string; lens_weights?: Record<string, number>; is_onboarded?: boolean }) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/onboarding`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
};

export const productAreas = {
  list: (orgId: string) => request<ProductArea[]>(`/orgs/${orgId}/product-areas`),
  create: (orgId: string, data: { name: string; description?: string }) =>
    request<ProductArea>(`/orgs/${orgId}/product-areas`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  delete: (orgId: string, areaId: string) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/product-areas/${areaId}`, { method: "DELETE" }),
};

export const dataSources = {
  list: (orgId: string) => request<DataSource[]>(`/orgs/${orgId}/data-sources`),
  create: (orgId: string, data: { source_type: string; name: string }) =>
    request<DataSource>(`/orgs/${orgId}/data-sources`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  delete: (orgId: string, sourceId: string) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/data-sources/${sourceId}`, { method: "DELETE" }),
};

export const auth = {
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  register: (email: string, name: string, password: string, org_name?: string) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, name, password, org_name }),
    }),

  me: () => request<UserResponse>("/auth/me"),

  orgs: () => request<OrgOption[]>("/auth/orgs"),

  selectOrg: (org_id: string) =>
    request<AuthResponse>("/auth/select-org", {
      method: "POST",
      body: JSON.stringify({ org_id }),
    }),
};

// --- Friction ---
export interface FrictionSignal {
  id: string;
  signal_type: string;
  severity: string;
  product_area: string | null;
  funnel_step: string | null;
  current_rate: number;
  baseline_rate: number;
  deviation_score: number;
  affected_users: number;
  description: string | null;
  evidence: Record<string, unknown>;
  status: string;
  detected_at: string;
  resolved_at: string | null;
}

export const friction = {
  list: (orgId: string, params?: { severity?: string; status?: string }) => {
    const query = new URLSearchParams(params as Record<string, string>).toString();
    return request<{ items: FrictionSignal[]; total: number }>(
      `/orgs/${orgId}/friction-reports${query ? `?${query}` : ""}`,
    );
  },
  updateStatus: (orgId: string, signalId: string, status: string) =>
    request(`/orgs/${orgId}/friction-reports/${signalId}/status?new_status=${status}`, {
      method: "PATCH",
    }),
};

// --- Insights ---
export interface Insight {
  id: string;
  insight_type: string;
  title: string;
  summary: string;
  detail: string;
  product_area: string | null;
  confidence: number;
  source_count: number;
  academic_perspective: string | null;
  business_perspective: string | null;
  ux_perspective: string | null;
  status: string;
  generated_at: string;
  created_at: string;
}

export const insights = {
  list: (orgId: string, params?: { insight_type?: string; status?: string }) => {
    const query = new URLSearchParams(params as Record<string, string>).toString();
    return request<{ items: Insight[]; total: number }>(
      `/orgs/${orgId}/insights${query ? `?${query}` : ""}`,
    );
  },
  get: (orgId: string, insightId: string) =>
    request<Insight>(`/orgs/${orgId}/insights/${insightId}`),
};

// --- Scores ---
export interface PriorityScore {
  id: string;
  product_area: string;
  score: number;
  rank: number;
  friction_score: number;
  voc_score: number;
  competitive_score: number;
  telemetry_score: number;
  strategic_score: number;
  recommendation: string | null;
  scored_at: string;
}

export interface ExperimentRecommendation {
  id: string;
  title: string;
  hypothesis: string;
  product_area: string | null;
  expected_impact: string;
  expected_revenue_impact: number | null;
  confidence: number;
  effort_estimate: string;
  variants: Record<string, string>;
  status: string;
  rank: number;
  generated_at: string;
}

export const scores = {
  priorities: (orgId: string) =>
    request<PriorityScore[]>(`/orgs/${orgId}/scores/priorities`),
  experiments: (orgId: string) =>
    request<ExperimentRecommendation[]>(`/orgs/${orgId}/scores/experiments`),
  recordOutcome: (orgId: string, data: Record<string, unknown>) =>
    request(`/orgs/${orgId}/scores/outcomes`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// --- Competitors ---
export interface Competitor {
  id: string;
  name: string;
  slug: string;
  website_url: string | null;
  description: string | null;
  is_active: boolean;
}

export interface CompetitorChange {
  id: string;
  competitor_id: string;
  change_type: string;
  title: string;
  description: string;
  significance: string;
  source_url: string | null;
  detected_at: string;
}

export const competitors = {
  list: (orgId: string) => request<Competitor[]>(`/orgs/${orgId}/competitors`),
  create: (orgId: string, data: { name: string; website_url?: string; description?: string }) =>
    request<Competitor>(`/orgs/${orgId}/competitors`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  delete: (orgId: string, competitorId: string) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/competitors/${competitorId}`, { method: "DELETE" }),
  changes: (orgId: string, competitorId: string) =>
    request<CompetitorChange[]>(`/orgs/${orgId}/competitors/${competitorId}/changes`),
};

// --- Knowledge ---
export interface KnowledgeDocument {
  id: string;
  title: string;
  doc_type: string;
  file_type: string | null;
  summary: string | null;
  key_findings: Record<string, unknown>;
  chunk_count: number;
  status: string;
}

export interface SearchResult {
  document_id: string;
  document_title: string;
  chunk_text: string;
  section: string | null;
  relevance_score: number;
}

// --- Battlecards ---
export interface Battlecard {
  competitor_id: string;
  competitor_name: string;
  generated_at: string;
  overview: string;
  strengths: string[];
  weaknesses: string[];
  differentiators: string[];
  objections: { objection: string; response: string }[];
  win_themes: string[];
  loss_reasons: string[];
  pricing_comparison: string;
}

export const battlecards = {
  list: (orgId: string) => request<Competitor[]>(`/orgs/${orgId}/competitors`),
  generate: (orgId: string, competitorId: string) =>
    request<Battlecard>(`/orgs/${orgId}/battlecards/${competitorId}`, { method: "POST" }),
  get: (orgId: string, competitorId: string) =>
    request<Battlecard>(`/orgs/${orgId}/battlecards/${competitorId}`),
};

// --- Digests ---
export interface WeeklyDigest {
  id: string;
  title: string;
  content: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  sections: {
    tldr: string;
    competitive: string;
    friction: string;
    experiments: string;
    priorities: string;
  };
}

export const digests = {
  list: (orgId: string) => request<WeeklyDigest[]>(`/orgs/${orgId}/digests`),
  latest: (orgId: string) => request<WeeklyDigest>(`/orgs/${orgId}/digests/latest`),
  generate: (orgId: string) =>
    request<WeeklyDigest>(`/orgs/${orgId}/digests/generate`, { method: "POST" }),
};

// --- Knowledge ---
export const knowledge = {
  list: (orgId: string) => request<KnowledgeDocument[]>(`/orgs/${orgId}/knowledge`),
  search: (orgId: string, query: string) =>
    request<SearchResult[]>(`/orgs/${orgId}/knowledge/search`, {
      method: "POST",
      body: JSON.stringify({ query, limit: 10 }),
    }),
  upload: async (orgId: string, file: File, title: string, docType: string): Promise<KnowledgeDocument> => {
    const token = typeof window !== "undefined" ? localStorage.getItem("observatory_token") : null;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("doc_type", docType);
    const res = await fetch(`${API_BASE}/api/v1/orgs/${orgId}/knowledge/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(res.status, body.detail || res.statusText);
    }
    return res.json();
  },
};

// --- Research ---
export interface ResearchBrief {
  id: string;
  title: string;
  knowledge_gap: string;
  objective: string;
  methodology: string;
  sample_description: string;
  sample_size: number;
  estimated_cost: number;
  estimated_cost_currency: string;
  expected_value: string;
  expected_value_rationale: string;
  product_area: string | null;
  priority: string;
  status: string;
  evidence_sources: Record<string, unknown>;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface KnowledgeGap {
  title: string;
  description: string;
  methodology: string;
  priority: string;
  estimated_value: string;
  related_area: string;
}

export interface OutcomeStats {
  period_days: number;
  total_outcomes: number;
  by_outcome: Record<string, number>;
  by_type: Record<string, Record<string, number>>;
  hit_rate: number;
  total_revenue_impact: number;
}

export const research = {
  briefs: (orgId: string, params?: { status?: string; priority?: string }) => {
    const query = new URLSearchParams(params as Record<string, string>).toString();
    return request<ResearchBrief[]>(`/research/briefs${query ? `?${query}` : ""}`);
  },
  getBrief: (orgId: string, briefId: string) =>
    request<ResearchBrief>(`/research/briefs/${briefId}`),
  createBrief: (orgId: string, data: { title: string; knowledge_gap: string; methodology?: string; product_area?: string; priority?: string }) =>
    request<{ id: string; title: string; status: string }>(`/research/briefs`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateBrief: (orgId: string, briefId: string, data: { status?: string; priority?: string }) =>
    request(`/research/briefs/${briefId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  detectGaps: (orgId: string) =>
    request<{ gaps: KnowledgeGap[]; count: number }>(`/research/detect-gaps`, { method: "POST" }),
  generateBriefs: (orgId: string) =>
    request<{ gaps_detected: number; briefs_generated: number; brief_ids: string[] }>(`/research/generate-briefs`, { method: "POST" }),
  outcomeStats: (orgId: string) =>
    request<OutcomeStats>(`/orgs/${orgId}/scores/outcome-stats`),
};

// --- AI (Claude) ---
export interface CompetitorAnalysis {
  overview: string;
  strengths: string[];
  weaknesses: string[];
  differentiators: string[];
  objections: { objection: string; response: string }[];
  win_themes: string[];
  loss_reasons: string[];
  pricing_posture: string;
  lens_analysis?: Record<string, string>;
  three_lens_analysis?: Record<string, string>;
  recommended_actions: string[];
}

export interface FrictionScenario {
  title: string;
  product_area: string;
  severity: string;
  description: string;
  evidence_needed: string;
  three_lens_analysis: { academic: string; business: string; ux: string };
}

export interface ExperimentIdea {
  title: string;
  hypothesis: string;
  product_area: string;
  variants: string[];
  expected_impact: string;
  effort: string;
  confidence: number;
}

export interface AISummary {
  competitors_analyzed: number;
  friction_scenarios: number;
  experiment_ideas: number;
  has_api_key: boolean;
}

export const ai = {
  summary: (orgId: string) => request<AISummary>(`/orgs/${orgId}/ai/summary`),
  analyzeCompetitor: (orgId: string, competitorId: string) =>
    request<{ analysis: CompetitorAnalysis; generated_at: string }>(
      `/orgs/${orgId}/competitors/${competitorId}/analyze`,
      { method: "POST" },
    ),
  getCompetitorAnalysis: (orgId: string, competitorId: string) =>
    request<{ analysis: CompetitorAnalysis; generated_at: string } | null>(
      `/orgs/${orgId}/competitors/${competitorId}/analysis`,
    ),
  frictionScenarios: {
    generate: (orgId: string) =>
      request<{ scenarios: FrictionScenario[]; generated_at: string }>(
        `/orgs/${orgId}/ai/friction-scenarios`,
        { method: "POST" },
      ),
    get: (orgId: string) =>
      request<{ scenarios: FrictionScenario[]; generated_at: string } | null>(
        `/orgs/${orgId}/ai/friction-scenarios`,
      ),
  },
  experimentIdeas: {
    generate: (orgId: string) =>
      request<{ ideas: ExperimentIdea[]; generated_at: string }>(
        `/orgs/${orgId}/ai/experiment-ideas`,
        { method: "POST" },
      ),
    get: (orgId: string) =>
      request<{ ideas: ExperimentIdea[]; generated_at: string } | null>(
        `/orgs/${orgId}/ai/experiment-ideas`,
      ),
  },
  ask: (orgId: string, question: string) =>
    request<{ answer: string }>(`/orgs/${orgId}/ai/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  insights: {
    generate: (orgId: string) =>
      request<{ items: Record<string, unknown>[]; generated_at: string }>(
        `/orgs/${orgId}/ai/insights`,
        { method: "POST" },
      ),
    get: (orgId: string) =>
      request<{ items: Record<string, unknown>[]; generated_at: string | null }>(
        `/orgs/${orgId}/ai/insights`,
      ),
  },
  researchGaps: {
    generate: (orgId: string) =>
      request<{ items: Record<string, unknown>[]; generated_at: string }>(
        `/orgs/${orgId}/ai/research-gaps`,
        { method: "POST" },
      ),
    get: (orgId: string) =>
      request<{ items: Record<string, unknown>[]; generated_at: string | null }>(
        `/orgs/${orgId}/ai/research-gaps`,
      ),
  },
  digest: {
    generate: (orgId: string) =>
      request<{ digest: Record<string, unknown>; generated_at: string }>(
        `/orgs/${orgId}/ai/digest`,
        { method: "POST" },
      ),
    get: (orgId: string) =>
      request<{ digest: Record<string, unknown> | null; generated_at: string | null }>(
        `/orgs/${orgId}/ai/digest`,
      ),
  },
};

export const org = {
  setApiKey: (orgId: string, api_key: string) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/api-key`, {
      method: "POST",
      body: JSON.stringify({ anthropic_api_key: api_key }),
    }),
};

export interface ServiceKey {
  id: string;
  name: string;
  key?: string;
  created_at: string;
  last_used_at: string | null;
}

export const serviceKeys = {
  list: (orgId: string) => request<ServiceKey[]>(`/orgs/${orgId}/service-keys`),
  create: (orgId: string, name: string) =>
    request<ServiceKey>(`/orgs/${orgId}/service-keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  delete: (orgId: string, keyId: string) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/service-keys/${keyId}`, { method: "DELETE" }),
};

// --- Intelligence ---
export interface IntelFeed {
  id: string;
  source: string;
  query: string;
  content: string;
  competitor_id: string | null;
  created_at: string;
}

export const intel = {
  feeds: (orgId: string) => request<IntelFeed[]>(`/orgs/${orgId}/intel/feeds`),
  feed: (orgId: string, feedId: string) => request<IntelFeed>(`/orgs/${orgId}/intel/feeds/${feedId}`),
  scrapeCompetitor: (orgId: string, data: { competitor_id?: string; url?: string }) =>
    request(`/orgs/${orgId}/intel/scrape-competitor`, { method: "POST", body: JSON.stringify(data) }),
  crawlCompetitor: (orgId: string, data: { competitor_id?: string; url?: string; max_pages?: number }) =>
    request(`/orgs/${orgId}/intel/crawl-competitor`, { method: "POST", body: JSON.stringify(data) }),
  webSearch: (orgId: string, data: { query: string }) =>
    request(`/orgs/${orgId}/intel/web-search`, { method: "POST", body: JSON.stringify(data) }),
  competitorNews: (orgId: string, data: { competitor_id: string }) =>
    request(`/orgs/${orgId}/intel/competitor-news`, { method: "POST", body: JSON.stringify(data) }),
  hackernewsScan: (orgId: string, data: { query?: string }) =>
    request(`/orgs/${orgId}/intel/hackernews-scan`, { method: "POST", body: JSON.stringify(data) }),
  redditScan: (orgId: string, data: { query?: string; subreddit?: string }) =>
    request(`/orgs/${orgId}/intel/reddit-scan`, { method: "POST", body: JSON.stringify(data) }),
  scanReviews: (orgId: string, data: { competitor_id: string; platform?: string }) =>
    request(`/orgs/${orgId}/intel/scan-reviews`, { method: "POST", body: JSON.stringify(data) }),
  academicSearch: (orgId: string, data: { query: string }) =>
    request(`/orgs/${orgId}/intel/academic-search`, { method: "POST", body: JSON.stringify(data) }),
  deepAnalysis: (orgId: string, data: { competitor_id: string }) =>
    request(`/orgs/${orgId}/intel/deep-analysis`, { method: "POST", body: JSON.stringify(data) }),
};

// --- API Keys ---
export const apiKeys = {
  setFirecrawl: (orgId: string, data: { api_key: string }) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/api-keys/firecrawl`, { method: "POST", body: JSON.stringify(data) }),
  setPerplexity: (orgId: string, data: { api_key: string }) =>
    request<{ ok: boolean }>(`/orgs/${orgId}/api-keys/perplexity`, { method: "POST", body: JSON.stringify(data) }),
};

export default { auth, friction, insights, scores, competitors, knowledge, battlecards, digests, research, onboarding, productAreas, dataSources, ai, org, serviceKeys, intel, apiKeys };
