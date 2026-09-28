type PrimitiveMetric = string | number | boolean | null;

export type PresentedMetric = {
  label: string;
  source: string;
  value: string;
};

const LABELS: Record<string, string> = {
  estimated_daily_revenue: "预估日营业额",
  estimated_daily_gross_profit: "预估日毛利",
  daily_rent: "日均房租",
  "revenue.total_revenue": "样本营业额",
  "revenue.order_count": "订单量",
  "revenue.avg_order_value": "平均客单价",
  "survival.projected_monthly_revenue": "月营业额预测",
  "survival.projected_monthly_profit": "月利润预测",
  "survival.break_even_daily_revenue": "日保本营业额",
  "survival.break_even_daily_orders": "日保本订单量",
  "survival.cash_runway_months": "现金可支撑月数",
  "channels.delivery_revenue_share": "外卖营收占比",
  "channels.delivery_contribution_margin": "外卖贡献毛利率",
  "discounts.total_discount_amount": "优惠让利金额",
  "reviews.negative_review_count": "中差评数量",
  "time_patterns.trend.status": "营收趋势"
};

const OPERATING_PRIORITIES = [
  "revenue.total_revenue",
  "revenue.order_count",
  "revenue.avg_order_value",
  "survival.projected_monthly_profit",
  "survival.break_even_daily_revenue",
  "channels.delivery_contribution_margin",
  "discounts.total_discount_amount",
  "reviews.negative_review_count"
];

export function presentMetric(path: string, value: PrimitiveMetric): PresentedMetric {
  return {
    label: LABELS[path] ?? humanize(path),
    source: `metrics.${path}`,
    value: formatMetricValue(path, value)
  };
}

export function presentHistoryMetrics(metrics: Record<string, unknown>): PresentedMetric[] {
  const preferred = OPERATING_PRIORITIES.flatMap((path) => {
    const value = readPath(metrics, path);
    return isPrimitive(value) ? [presentMetric(path, value)] : [];
  });
  if (preferred.length) return preferred;
  return flatten(metrics).slice(0, 8).map(({ path, value }) => presentMetric(path, value));
}

function readPath(source: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => (
    current && typeof current === "object" && !Array.isArray(current)
      ? (current as Record<string, unknown>)[key]
      : undefined
  ), source);
}

function flatten(source: Record<string, unknown>, prefix = ""): Array<{ path: string; value: PrimitiveMetric }> {
  return Object.entries(source).flatMap(([key, value]) => {
    if (key.startsWith("_")) return [];
    const path = prefix ? `${prefix}.${key}` : key;
    if (isPrimitive(value)) return [{ path, value }];
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return flatten(value as Record<string, unknown>, path);
    }
    return [];
  });
}

function isPrimitive(value: unknown): value is PrimitiveMetric {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function formatMetricValue(path: string, value: PrimitiveMetric): string {
  if (value === null) return "暂无数据";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") {
    return value === "growing" ? "增长" : value === "declining" ? "下降" : value === "stable" ? "平稳" : value;
  }
  if (/(margin|rate|share)/.test(path)) return `${(value * 100).toFixed(1)}%`;
  if (/(revenue|profit|rent|amount|cost|gap)/.test(path)) return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
  if (/(order_count|orders)/.test(path)) return `${value.toLocaleString("zh-CN")} 单`;
  if (path.endsWith("months")) return `${value.toLocaleString("zh-CN")} 个月`;
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function humanize(path: string): string {
  return path.split(".").at(-1)?.replace(/_/g, " ") ?? path;
}
