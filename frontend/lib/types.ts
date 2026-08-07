export type Stage = "pre_open" | "operating";

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
};

export type UploadedFileResult = {
  project_id: number;
  file_type: string;
  filename: string;
  storage_path: string;
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
