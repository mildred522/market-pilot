import type { SurvivalMetrics } from "@/lib/types";

const riskLabels = {
  stable: "当前投影已过保本线",
  watch: "低于保本线，需持续观察",
  high: "现金压力高，需设置止损"
};

function money(value: number) {
  return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
}

export function SurvivalPanel({ metrics }: { metrics: SurvivalMetrics }) {
  return (
    <section className="report-section survival-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Survival line</p>
          <h2>成本结构与保本线</h2>
        </div>
        <span className={`survival-status survival-${metrics.risk_level}`}>
          {riskLabels[metrics.risk_level]}
        </span>
      </div>
      <div className="survival-grid">
        <div><span>实际毛利率</span><strong>{(metrics.observed_gross_margin * 100).toFixed(1)}%</strong></div>
        <div><span>月固定成本</span><strong>{money(metrics.monthly_fixed_cost)}</strong></div>
        <div><span>月保本营业额</span><strong>{money(metrics.break_even_monthly_revenue)}</strong></div>
        <div><span>日保本营业额</span><strong>{money(metrics.break_even_daily_revenue)}</strong></div>
        <div><span>保本日订单</span><strong>{metrics.break_even_daily_orders} 单</strong></div>
        <div><span>月经营利润投影</span><strong className={metrics.projected_monthly_profit < 0 ? "negative-value" : "positive-value"}>{money(metrics.projected_monthly_profit)}</strong></div>
        <div><span>距离保本线</span><strong className={metrics.monthly_revenue_gap < 0 ? "negative-value" : "positive-value"}>{money(metrics.monthly_revenue_gap)}</strong></div>
        <div><span>现金可支撑</span><strong>{metrics.cash_runway_months === null ? "已自我覆盖" : `${metrics.cash_runway_months} 个月`}</strong></div>
      </div>
      <p className="survival-note">{metrics.assumption_note}</p>
    </section>
  );
}
