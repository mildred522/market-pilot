export type Stage = "pre_open" | "operating";

export type IntegrationStatus = {
  configured: boolean;
  source: "saved" | "runtime" | "environment" | null;
  model?: string | null;
  provider?: string;
  base_url?: string;
};

export type IntegrationTestResult = {
  ok: boolean;
  latency_ms: number;
  message: string;
  code?: string;
  details: {
    provider?: string;
    model?: string | null;
    sample_total?: number;
  };
};

export type DashboardOverview = {
  workspace: {
    name: string;
    role: string;
    account_mode: "local";
  };
  counts: {
    projects: number;
    pre_open_projects: number;
    operating_projects: number;
    analyses: number;
    uploaded_files: number;
    location_analyses: number;
  };
  integrations: {
    baidu: IntegrationStatus;
    agent: IntegrationStatus;
  };
  recent_analyses: Array<{
    id: number;
    project_id: number;
    project_name: string;
    stage: Stage;
    summary: string;
  }>;
};

export type Project = {
  id: number;
  name: string;
  stage: Stage;
};

export type PreOpenInput = {
  project_id: number;
  category: string;
  city: string;
  location_type: string;
  area_sqm: number;
  seats: number;
  monthly_rent: number;
  total_investment: number;
  own_capital: number;
  debt_amount: number;
  expected_daily_orders: number;
  expected_avg_order_value: number;
  expected_gross_margin: number;
  is_franchise: boolean;
  franchise_fee: number;
  competitor_count: number;
  storefront_visibility: string;
};

export type PreOpenReport = {
  analysis_id: number;
  project_id: number;
  stage: "pre_open";
  summary: string;
  metrics: Record<string, number>;
  risks: string[];
  actions: string[];
};

export type RevenuePoint = {
  date: string;
  revenue: number;
  orders: number;
};

export type MenuMatrixItem = {
  item_name: string;
  category: string;
  quantity: number;
  revenue: number;
  gross_profit: number;
  gross_margin: number;
  quadrant: "star" | "traffic" | "profit" | "problem";
};

export type OperatingMetrics = {
  revenue: {
    total_revenue: number;
    order_count: number;
    avg_order_value: number;
    daily_revenue: RevenuePoint[];
  };
  menu: {
    items: MenuMatrixItem[];
  };
  reviews: {
    topics: Record<string, number>;
    review_count: number;
    negative_review_count: number;
  };
  survival?: SurvivalMetrics;
  channels?: ChannelMetrics;
  time_patterns?: TimePatternMetrics;
  discounts?: DiscountMetrics;
  _agent?: AgentTrace;
};

export type AgentTrace = {
  mode: "llm" | "hybrid" | "deterministic";
  provider: string;
  model: string | null;
  prompt_version: string;
  selected_tools: string[];
  planning_used_llm: boolean;
  synthesis_used_llm: boolean;
  fallback_reasons: string[];
  duration_ms: number;
  run_id?: number;
};

export type DiscountSegment = {
  key: "regular" | "discounted";
  label: string;
  order_count: number;
  listed_amount: number;
  revenue: number;
  average_order_value: number;
  discount_amount: number;
  discount_rate: number;
  food_cost: number;
  contribution_profit: number;
  contribution_margin: number;
};

export type DiscountMetrics = {
  segments: DiscountSegment[];
  discounted_order_count: number;
  discounted_order_share: number;
  total_discount_amount: number;
  discounted_contribution_profit: number;
  discounted_contribution_margin: number;
  margin_gap_vs_regular: number | null;
  assumption_note: string;
};

export type DaypartMetric = {
  key: string;
  label: string;
  order_count: number;
  revenue: number;
  revenue_share: number;
  average_order_value: number;
};

export type RevenueAnomaly = {
  date: string;
  revenue: number;
  orders: number;
  direction: "high" | "low";
  deviation_from_median: number | null;
};

export type TimePatternMetrics = {
  observed_days: number;
  dayparts: DaypartMetric[];
  peak_daypart: string | null;
  peak_daypart_label: string | null;
  trend: {
    status: "insufficient_data" | "declining" | "stable" | "growing";
    change_rate: number | null;
    previous_average_revenue: number | null;
    recent_average_revenue: number | null;
    note: string;
  };
  anomalies: RevenueAnomaly[];
  coverage_note: string;
};

export type ChannelMetric = {
  channel: string;
  channel_type: "delivery" | "direct";
  order_count: number;
  revenue: number;
  revenue_share: number;
  average_order_value: number;
  food_cost: number;
  platform_fee: number;
  packaging_cost: number;
  contribution_profit: number;
  contribution_margin: number;
};

export type ChannelMetrics = {
  channels: ChannelMetric[];
  delivery_commission_rate: number;
  delivery_packaging_per_order: number;
  delivery_revenue: number;
  delivery_revenue_share: number;
  delivery_food_cost: number;
  delivery_platform_fee: number;
  delivery_packaging_cost: number;
  delivery_contribution_profit: number;
  delivery_contribution_margin: number;
  assumption_note: string;
};

export type SurvivalMetrics = {
  observed_days: number;
  observed_revenue: number;
  observed_food_cost: number;
  observed_gross_profit: number;
  observed_gross_margin: number;
  average_daily_revenue: number;
  projected_monthly_revenue: number;
  monthly_fixed_cost: number;
  break_even_monthly_revenue: number;
  break_even_daily_revenue: number;
  break_even_daily_orders: number;
  projected_monthly_profit: number;
  monthly_revenue_gap: number;
  cash_balance: number;
  cash_runway_months: number | null;
  risk_level: "stable" | "watch" | "high";
  assumption_note: string;
};

export type OperatingCostAssumptions = {
  monthly_rent: number;
  monthly_labor: number;
  monthly_utilities: number;
  monthly_marketing: number;
  other_fixed_costs: number;
  cash_balance: number;
  delivery_commission_rate: number;
  delivery_packaging_per_order: number;
  target_avg_order_value?: number;
  target_delivery_contribution_margin?: number;
  target_monthly_profit?: number;
};

export type AnalysisReport = {
  analysis_id: number;
  project_id: number;
  stage: Stage;
  summary: string;
  metrics: Record<string, number> | OperatingMetrics;
  evidence: string[];
  actions: string[];
  risks: string[];
  agent_trace?: AgentTrace | null;
};

export type AnalysisFollowupResponse = {
  answer: string;
  evidence_refs: string[];
  confidence: number;
  mode: "llm" | "deterministic" | "insufficient_data";
  steps: number;
  tool_calls: Array<{ tool: string; arguments: Record<string, unknown> }>;
  fallback_reason?: string;
  supporting_evidence?: string[];
  missing_metrics?: string[];
  available_sections?: string[];
  failure_detail?: {
    stage: string;
    reason: string;
    candidate: string | null;
  };
  prompt_version: string;
};

export type UploadedFileResult = {
  file_id: number;
  project_id: number;
  file_type: string;
  filename: string;
  columns: string[];
  required_columns: string[];
  suggested_mapping: Record<string, string>;
  missing_columns: string[];
  row_count: number;
};

export type OperatingFileSelection = {
  file_id: number;
  mapping: Record<string, string>;
};

export type FinanceAssumptions = {
  gross_margin?: number;
  labor_cost?: number;
  utilities_cost?: number;
  other_fixed_cost?: number;
  target_daily_orders?: number;
  monthly_rent?: number;
};

export type LocationRequestBase = {
  project_id: number;
  city: string;
  district: string;
  category: string;
  target_customer: string;
  planned_average_order_value: number;
  finance_assumptions?: FinanceAssumptions;
  coordinate_system: "bd09ll";
  radius_meters: number;
};

export type ManualLocationRequest = LocationRequestBase & {
  address?: string;
  latitude?: number;
  longitude?: number;
};

export type RecommendationRequest = LocationRequestBase & {
  candidate_count: number;
};

export type LocationEvidence = {
  source: string;
  label: string;
  observed_at: string;
  expires_at: string;
  query_scope: Record<string, unknown>;
  value: unknown;
};

export type LocationResult = {
  mode: "manual" | "recommendations";
  status: "completed" | "degraded" | "failed";
  analysis_id: number;
  input_scope: Record<string, unknown>;
  center?: { latitude: number; longitude: number; coordinate_system: "bd09ll"; source?: string };
  opportunity: { score?: number; conclusion?: string };
  confidence: { score?: number };
  finance: { feasibility?: string; assumptions_provided: boolean; metrics: Record<string, unknown>; disclaimer: string };
  dimension_breakdown: Record<string, unknown>;
  confidence_breakdown: Record<string, unknown>;
  evidence: LocationEvidence[];
  risks: string[];
  warnings: string[];
  recommendations: string[];
  transition_coordinates?: { latitude: number; longitude: number; coordinate_system: "bd09ll"; source?: string };
  candidates: LocationCandidate[];
};

export type LocationCandidate = {
  name: string;
  center: { latitude: number; longitude: number; coordinate_system: "bd09ll"; source?: string };
  transition_coordinates: { latitude: number; longitude: number; coordinate_system: "bd09ll"; source?: string };
  opportunity: { score?: number; conclusion?: string };
  confidence: { score?: number };
  finance: { feasibility?: string; assumptions_provided: boolean; metrics: Record<string, unknown>; disclaimer: string };
  dimension_breakdown: Record<string, unknown>;
  confidence_breakdown: Record<string, unknown>;
  evidence: LocationEvidence[];
  risks: string[];
  warnings: string[];
  recommendations: string[];
};
