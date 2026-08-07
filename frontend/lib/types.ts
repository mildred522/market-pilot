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
