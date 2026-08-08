import type { ChannelMetrics } from "@/lib/types";

function money(value: number) {
  return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
}

export function ChannelProfitPanel({ metrics }: { metrics: ChannelMetrics }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Channel contribution</p>
          <h2>渠道盈利对比</h2>
        </div>
        <p>外卖已扣除食材、平台佣金和包材；贡献利润尚未分摊固定成本。</p>
      </div>
      <div className="channel-table">
        <div className="channel-table-head" aria-hidden="true">
          <span>渠道</span><span>营收 / 占比</span><span>订单 / 客单</span><span>渠道费用</span><span>贡献利润</span>
        </div>
        {metrics.channels.map((channel) => (
          <div className="channel-row" key={channel.channel}>
            <div><strong>{channel.channel}</strong><small>{channel.channel_type === "delivery" ? "外卖" : "直销/堂食"}</small></div>
            <div><strong>{money(channel.revenue)}</strong><small>{(channel.revenue_share * 100).toFixed(1)}%</small></div>
            <div><strong>{channel.order_count} 单</strong><small>客单 {money(channel.average_order_value)}</small></div>
            <div><strong>{money(channel.platform_fee + channel.packaging_cost)}</strong><small>平台 {money(channel.platform_fee)} · 包材 {money(channel.packaging_cost)}</small></div>
            <div><strong className={channel.contribution_profit < 0 ? "negative-value" : "positive-value"}>{money(channel.contribution_profit)}</strong><small>贡献率 {(channel.contribution_margin * 100).toFixed(1)}%</small></div>
          </div>
        ))}
      </div>
    </section>
  );
}
