import type { TimePatternMetrics } from "@/lib/types";

function money(value: number) {
  return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
}

const TREND_LABELS = {
  insufficient_data: "数据不足",
  declining: "下降",
  stable: "基本稳定",
  growing: "增长"
};

export function TimePatternPanel({ metrics }: { metrics: TimePatternMetrics }) {
  const trend = metrics.trend;
  return (
    <section className="report-section time-pattern-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Revenue rhythm</p>
          <h2>营收时段与异常</h2>
        </div>
        <p>
          已观察 {metrics.observed_days} 个营业日
          {metrics.peak_daypart_label ? `，峰值在${metrics.peak_daypart_label}` : ""}。
        </p>
      </div>

      <div className="daypart-list">
        {metrics.dayparts.map((period) => (
          <div className="daypart-row" key={period.key}>
            <div><strong>{period.label}</strong><small>{period.order_count} 单 · 客单 {money(period.average_order_value)}</small></div>
            <div className="daypart-track" aria-label={`${period.label}营收占比 ${(period.revenue_share * 100).toFixed(1)}%`}>
              <span style={{ width: `${Math.max(period.revenue_share * 100, period.revenue > 0 ? 2 : 0)}%` }} />
            </div>
            <div><strong>{money(period.revenue)}</strong><small>{(period.revenue_share * 100).toFixed(1)}%</small></div>
          </div>
        ))}
      </div>

      <div className="trend-summary">
        <div>
          <span>样本趋势</span>
          <strong className={`trend-${trend.status}`}>{TREND_LABELS[trend.status]}</strong>
        </div>
        {trend.change_rate !== null ? (
          <p>
            前半段日均 {money(trend.previous_average_revenue ?? 0)}，后半段日均 {money(trend.recent_average_revenue ?? 0)}，
            变化 {trend.change_rate > 0 ? "+" : ""}{(trend.change_rate * 100).toFixed(1)}%。
          </p>
        ) : <p>{trend.note}</p>}
      </div>

      {metrics.anomalies.length > 0 ? (
        <div className="anomaly-list">
          <span>需复盘的异常营业日</span>
          {metrics.anomalies.map((item) => (
            <div key={item.date}>
              <strong>{item.date}</strong>
              <span>{money(item.revenue)} · {item.orders} 单</span>
              <em>{item.direction === "low" ? "异常偏低" : "异常偏高"}</em>
            </div>
          ))}
        </div>
      ) : null}
      <p className="time-pattern-note">{metrics.coverage_note}</p>
    </section>
  );
}
