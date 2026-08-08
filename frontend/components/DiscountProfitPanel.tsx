import type { DiscountMetrics } from "@/lib/types";

function money(value: number) {
  return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
}

export function DiscountProfitPanel({ metrics }: { metrics: DiscountMetrics }) {
  return (
    <section className="report-section discount-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Discount economics</p>
          <h2>折扣盈利对比</h2>
        </div>
        <p>
          {metrics.discounted_order_count > 0
            ? `${metrics.discounted_order_count} 单发生让利，占订单 ${(metrics.discounted_order_share * 100).toFixed(1)}%。`
            : "样本中未识别到低于菜单标价的订单。"}
        </p>
      </div>

      <div className="discount-table">
        <div className="discount-table-head" aria-hidden="true">
          <span>订单类型</span><span>订单 / 实收</span><span>让利</span><span>贡献利润</span><span>贡献率</span>
        </div>
        {metrics.segments.map((segment) => (
          <div className="discount-row" key={segment.key}>
            <div><strong>{segment.label}</strong><small>客单 {money(segment.average_order_value)}</small></div>
            <div><strong>{segment.order_count} 单</strong><small>{money(segment.revenue)}</small></div>
            <div><strong>{money(segment.discount_amount)}</strong><small>{(segment.discount_rate * 100).toFixed(1)}%</small></div>
            <div><strong className={segment.contribution_profit < 0 ? "negative-value" : "positive-value"}>{money(segment.contribution_profit)}</strong><small>食材 {money(segment.food_cost)}</small></div>
            <div><strong>{(segment.contribution_margin * 100).toFixed(1)}%</strong><small>未分摊固定成本</small></div>
          </div>
        ))}
      </div>
      <p className="time-pattern-note">{metrics.assumption_note}</p>
    </section>
  );
}
