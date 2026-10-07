export type Stage = "pre_open" | "operating";

export type AuthenticatedUser = {
  id: string;
  email: string;
  is_admin: boolean;
};

export type CommerceBenchmarkSnapshotSummary = {
  snapshot_id: string;
  source_type: string;
  schema_version: string;
  content_hash: string;
  created_at: string;
  period_start: string | null;
  period_end: string | null;
  timezone: string | null;
  capabilities: string[];
  row_counts: Record<string, number>;
};

export type CommerceProductSalesMetric = {
  item_level: "product" | "sku";
  item_id: string;
  product_id: string;
  category_name: string | null;
  units_sold: number | string;
  order_count: number;
  gross_amount: number | string;
  average_unit_price: number | string | null;
  seller_count: number;
  freight_amount: number | string | null;
  currency: string | null;
};

export type CommerceProductSalesReport = {
  snapshot_id: string;
  window: { start: string; end: string };
  item_level: "product" | "sku";
  metrics: CommerceProductSalesMetric[];
  included_order_count: number;
  excluded_order_count: number;
};

export type CommerceCategorySalesReport = {
  snapshot_id: string;
  window: { start: string; end: string };
  categories: Array<{
    category_name: string | null;
    product_count: number;
    units_sold: number | string;
    order_count: number;
    gross_amount: number | string;
    seller_count: number;
    currency: string | null;
  }>;
  included_order_count: number;
  excluded_order_count: number;
};

export type CommerceCategoryTrendMetric = {
  category_name: string | null;
  product_count: number;
  units_sold: number | string;
  order_count: number;
  gross_amount: number | string;
  currency: string | null;
};

export type CommerceCategoryTrendReport = {
  snapshot_id: string;
  current_window: { start: string; end: string };
  baseline_window: { start: string; end: string };
  trends: Array<{
    category_name: string | null;
    current: CommerceCategoryTrendMetric | null;
    previous: CommerceCategoryTrendMetric | null;
    units_growth_rate: number | string | null;
    gross_amount_growth_rate: number | string | null;
    order_growth_rate: number | string | null;
  }>;
  included_order_count: number;
  excluded_order_count: number;
};

export type CommerceComparisonWindows = {
  snapshot_id: string;
  baseline_window: { start: string; end: string };
  current_window: { start: string; end: string };
  selection_method: "latest_dense_28d" | "split_coverage";
  baseline_order_count: number;
  current_order_count: number;
  warning: string | null;
};

export type CommerceItemLevel = "product" | "sku";

export type CommerceInteractionRequest = {
  question: string;
  interaction: {
    mode: "talk" | "plan";
    scope: { mode: "benchmark"; project_id: number; snapshot_id: string };
  };
  previous_window: { start: string; end: string };
  current_window: { start: string; end: string };
  item_level: CommerceItemLevel;
};

export type CommerceTalkResponse = {
  status: "completed" | "insufficient_data" | "tool_failure";
  intent: "unsupported" | "sales" | "category_sales" | "category_trends" | "trends" | "hot_products" | "mixed";
  selected_tools: string[];
  query_spec: {
    semantic_version: string;
    metric_codes: string[];
    item_level: "product" | "sku";
    result_grain: "sku" | "product" | "category";
    matched_aliases: string[];
    definitions: string[];
    includes: string[];
    excludes: string[];
    execution_policy: string;
    snapshot_id: string | null;
    scope_mode: "benchmark" | "merchant" | null;
    previous_window: { start: string; end: string } | null;
    current_window: { start: string; end: string } | null;
    source_type: string | null;
    time_basis: string | null;
    order_statuses: string[];
    dimensions: string[];
    evidence_fields: string[];
    currency_policy: string | null;
  } | null;
  executions: Array<{
    tool_name: string;
    status: "completed" | "degraded" | "failed";
    data: {
      metrics?: CommerceProductSalesMetric[];
      categories?: CommerceCategorySalesReport["categories"];
      category_trends?: Array<{
        category_name: string | null;
        current: CommerceCategoryTrendMetric | null;
        previous: CommerceCategoryTrendMetric | null;
        units_growth_rate: number | string | null;
        gross_amount_growth_rate: number | string | null;
        order_growth_rate: number | string | null;
      }>;
      included_order_count?: number;
      excluded_order_count?: number;
      items?: CommerceProductTrendReport["trends"];
      candidates?: CommerceHotProductCandidate[];
    } | null;
    evidence: string[];
    warnings: string[];
    error_code: string | null;
    duration_ms: number;
  }>;
  suggestions: string[];
  limitations: string[];
};

export type CommercePlanResponse = {
  id: number;
  project_id: number;
  snapshot_id: string;
  scope_mode: "benchmark" | "merchant";
  question: string;
  status: "draft" | "approved" | "insufficient_data";
  title: string;
  objective: string;
  steps: Array<{
    priority: "high" | "medium" | "low";
    action: string;
    rationale: string;
    success_signal: string;
    evidence: string[];
  }>;
  evidence: string[];
  limitations: string[];
  created_at: string;
  updated_at: string;
  approved_at: string | null;
};

export type CommercePlanSummary = Pick<
  CommercePlanResponse,
  "id" | "project_id" | "snapshot_id" | "status" | "title" | "question" | "created_at" | "approved_at"
>;

export type CommercePlanListResponse = {
  items: CommercePlanSummary[];
  next_offset: number | null;
};

export type CommercePlanPracticeCreate = {
  step_index: number;
  kind: "scenario" | "reflection";
  note: string;
};

export type CommercePlanPracticeRecord = CommercePlanPracticeCreate & {
  id: number;
  plan_id: number;
  source_type: "benchmark_simulation";
  recorded_by_user_id: string | null;
  created_at: string;
};

export type CommercePlanPracticeListResponse = {
  items: CommercePlanPracticeRecord[];
  next_offset: number | null;
};

export type CommerceHotProductCandidate = {
  rank: number;
  item_level: "product" | "sku";
  item_id: string;
  product_id: string;
  category_name: string | null;
  labels: string[];
  confidence: "low" | "medium" | "high";
  current: CommerceProductSalesMetric;
  trend: {
    current: CommerceProductSalesMetric;
    previous: CommerceProductSalesMetric | null;
    units_growth_rate: number | string | null;
    gross_amount_growth_rate: number | string | null;
    order_growth_rate: number | string | null;
  };
  evidence: string[];
};

export type CommerceHotProductReport = {
  snapshot_id: string;
  current_window: { start: string; end: string };
  baseline_window: { start: string; end: string };
  item_level: "product" | "sku";
  candidates: CommerceHotProductCandidate[];
  included_order_count: number;
  excluded_order_count: number;
};

export type CommerceProductTrendReport = {
  snapshot_id: string;
  current_window: { start: string; end: string };
  baseline_window: { start: string; end: string };
  item_level: "product" | "sku";
  trends: Array<{
    item_level: "product" | "sku";
    item_id: string;
    product_id: string;
    category_name: string | null;
    current: CommerceProductSalesMetric | null;
    previous: CommerceProductSalesMetric | null;
    units_growth_rate: number | string | null;
    gross_amount_growth_rate: number | string | null;
    order_growth_rate: number | string | null;
  }>;
  included_order_count: number;
  excluded_order_count: number;
};

export type CommerceSelectionRecommendationReport = {
  snapshot_id: string;
  current_window: { start: string; end: string };
  baseline_window: { start: string; end: string };
  item_level: "product" | "sku";
  recommendations: Array<{
    rank: number;
    recommendation_type: "verify_growth" | "validate_new_product" | "protect_winner" | "review_decline";
    priority: "high" | "medium" | "low";
    item_level: "product" | "sku";
    item_id: string;
    product_id: string;
    category_name: string | null;
    title: string;
    action: string;
    rationale: string;
    evidence: string[];
    risk_flags: string[];
    current: CommerceProductSalesMetric | null;
    trend: CommerceProductTrendReport["trends"][number];
  }>;
  included_order_count: number;
  excluded_order_count: number;
};

export type IntegrationStatus = {
  configured: boolean;
  source: "saved" | "runtime" | "environment" | null;
  model?: string | null;
  provider?: string;
  base_url?: string;
  role_models?: {
    planner: string | null;
    synthesizer: string | null;
    followup: string | null;
  };
  effective_role_models?: {
    planner: string | null;
    synthesizer: string | null;
    followup: string | null;
  };
};

export type KnowledgeRagStatus = {
  enabled: boolean;
  configured: boolean;
  collection: string;
  dense_model: string;
  reranker_model: string | null;
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
    account_mode: "authenticated";
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
    knowledge_rag: KnowledgeRagStatus;
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

export type ProjectHistoryItem = Project & {
  created_at: string;
  updated_at: string;
};

export type ProjectHistoryPage = {
  items: ProjectHistoryItem[];
  next_offset: number | null;
};

export type AnalysisHistoryItem = {
  id: number;
  stage: Stage;
  summary: string;
  created_at: string;
  conversation_id: number | null;
  conversation_updated_at: string | null;
};

export type ProjectAnalyses = {
  project: ProjectHistoryItem;
  items: AnalysisHistoryItem[];
};

export type ConversationMessage = {
  id: number;
  role: "user" | "assistant";
  status: "completed" | "pending" | "failed";
  content: string;
  mode: string;
  answer_version_id: number | null;
  evidence_refs: string[];
  created_at: string;
};

export type ConversationHistory = {
  conversation_id: number | null;
  items: ConversationMessage[];
  next_before_message_id: number | null;
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
  request_id?: string;
  mode: "llm" | "hybrid" | "deterministic";
  status?: "completed" | "degraded" | "failed";
  provider: string;
  model: string | null;
  prompt_version: string;
  selected_tools: string[];
  planning_used_llm: boolean;
  synthesis_used_llm: boolean;
  fallback_reasons: string[];
  tool_executions?: Array<{
    tool_name: string;
    output_section: string;
    status: "completed" | "degraded" | "failed";
    evidence_count: number;
    warnings: string[];
    error_code: string | null;
    recoverable: boolean;
    duration_ms: number;
    from_cache: boolean;
  }>;
  replan_count?: number;
  replan?: {
    trigger: "recoverable_tool_failure";
    initial_tools: string[];
    failed_tools: string[];
    revised_tools: string[];
    outcome: "recovered" | "failed";
  } | null;
  duration_ms: number;
  run_id?: number;
};

export type AgentRunUsage = {
  model_calls: number;
  tool_calls: number;
  replan_count: number;
  output_repair_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  token_usage_complete: boolean;
};

export type AgentRunSummary = {
  request_id: string;
  project_id: number;
  analysis_id: number;
  run_id: number | null;
  operation: "operating_analysis" | "followup" | "confirmed_correction";
  status: "completed" | "degraded" | "failed";
  created_at: string;
  duration_ms: number;
  usage: AgentRunUsage;
};

export type AgentRunStage = {
  stage: "plan" | "model" | "tool" | "retrieve" | "replan" | "verify" | "fallback";
  label: string;
  status: "completed" | "degraded" | "failed";
  duration_ms: number | null;
  public_detail: string | null;
  role: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  retry_count: number | null;
  error_code: string | null;
};

export type AgentRunDetail = AgentRunSummary & {
  initial_plan: {
    intent: string;
    goal: string;
    workflow: string | null;
    dimensions: string[];
    tools: string[];
    missing_inputs: string[];
    requires_external_api: boolean;
  };
  revised_plan: {
    intent: string;
    goal: string;
    workflow: string | null;
    dimensions: string[];
    tools: string[];
    missing_inputs: string[];
    requires_external_api: boolean;
  } | null;
  timeline_order: "logical";
  timeline: AgentRunStage[];
  verification: { failure_count: number; passed: boolean };
  fallback_reasons: string[];
  selected_memory_count: number;
  budget: {
    limits: Record<string, number>;
    used: Record<string, number>;
    exhausted_dimensions: string[];
    evidence_truncated: boolean;
  };
  planning_disclosure: {
    candidate_workflow_count?: number;
    catalog_characters?: number;
    legacy_catalog_characters?: number;
    reduction_percent?: number;
  };
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

export type OperatingAnalysisMode = "full" | "focused";

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
  conversation_id?: number;
  answer: string;
  evidence_refs: string[];
  confidence: number;
  mode: "llm" | "deterministic" | "insufficient_data" | "confirmation_required";
  quality?: "complete" | "repaired" | "partial" | "insufficient" | "confirmation_required";
  sections?: FollowupSections;
  answer_version_id?: number;
  parent_version_id?: number | null;
  revision_plan?: {
    revision_type: "initial" | "rewrite_only" | "recompose_with_existing_evidence" | "retrieve_more_evidence" | "recompute_metrics";
    objective: string;
    requires_confirmation: boolean;
  };
  memory_updates?: Array<{ id: number; type: string; status: string }>;
  correction_proposals?: CorrectionProposal[];
  steps: number;
  tool_calls: Array<{ tool: string; arguments: Record<string, unknown> }>;
  fallback_reason?: string;
  supporting_evidence?: string[];
  missing_metrics?: string[];
  missing_evidence?: Array<"metric_history" | "external_industry_context" | "location_competitors">;
  available_sections?: string[];
  agent_trace?: {
    replan_count?: number;
    output_repair_count?: number;
    evidence_events?: Array<{
      capability: "metric_history" | "external_industry_context" | "location_competitors";
      requirement: "required" | "optional";
      status: "completed" | "failed";
      evidence_refs: string[];
      error: { code: string | null; message: string | null } | null;
    }>;
  };
  failure_detail?: {
    stage: string;
    reason: string;
  };
  prompt_version: string;
};

export type CorrectionProposal = {
  id: number;
  source_analysis_id: number;
  source_answer_version_id: number;
  field: "monthly_rent" | "monthly_labor" | "monthly_utilities" | "monthly_marketing" | "other_fixed_costs" | "cash_balance" | "delivery_commission_rate" | "delivery_packaging_per_order";
  old_value: number;
  new_value: number;
  reason: string;
  status: "pending" | "applying" | "applied" | "rejected" | "failed";
  idempotency_key: string;
  applied_analysis_id: number | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type CorrectionConfirmation = {
  proposal: CorrectionProposal;
  analysis_id: number;
  source_analysis_id: number;
  summary: string;
  metric_changes: Array<{
    path: string;
    old_value: unknown;
    new_value: unknown;
  }>;
};

export type FollowupSections = {
  data_findings: Array<{
    text: string;
    evidence_refs: string[];
    scope?: "current_report" | "external" | "history" | "reference" | "mixed";
  }>;
  general_advice: string[];
  missing_information: string[];
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
