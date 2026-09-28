import Link from "next/link";
import { ActionList } from "@/components/ActionList";
import { EvidencePanel } from "@/components/EvidencePanel";
import { MenuMatrix } from "@/components/MenuMatrix";
import { MetricCards } from "@/components/MetricCards";
import type { Metric } from "@/components/MetricCards";
import { RevenueChart } from "@/components/RevenueChart";
import { ReviewTopics } from "@/components/ReviewTopics";
import { RiskPanel } from "@/components/RiskPanel";
import { SurvivalPanel } from "@/components/SurvivalPanel";
import { ChannelProfitPanel } from "@/components/ChannelProfitPanel";
import { TimePatternPanel } from "@/components/TimePatternPanel";
import { DiscountProfitPanel } from "@/components/DiscountProfitPanel";
import { AgentRunStatus } from "@/components/AgentRunStatus";
import { AnalysisFollowup } from "@/components/AnalysisFollowup";
import type { AnalysisReport, OperatingMetrics } from "@/lib/types";
import { presentMetric } from "@/lib/metric-presentation";

function isOperatingMetrics(metrics: AnalysisReport["metrics"]): metrics is OperatingMetrics {
  return "revenue" in metrics && "menu" in metrics && "reviews" in metrics;
}

function money(value: number) {
  const absolute = Math.abs(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  return `${value < 0 ? "-" : ""}¥${absolute}`;
}

const HEALTH_LABELS = {
  stable: "已越过保本线",
  watch: "接近经营警戒线",
  high: "现金与利润承压"
};

export function AgentReport({ report }: { report: AnalysisReport }) {
  const isOperating = report.stage === "operating" && isOperatingMetrics(report.metrics);
  const operatingMetrics: OperatingMetrics | null = isOperating
    ? (report.metrics as OperatingMetrics)
    : null;
  const agentTrace = report.agent_trace ?? operatingMetrics?._agent ?? null;
  const survival = operatingMetrics?.survival;
  const metricCards: Metric[] = operatingMetrics
    ? [
        {
          label: "样本营收",
          value: money(operatingMetrics.revenue.total_revenue),
          hint: `${operatingMetrics.revenue.order_count} 笔订单`
        },
        {
          label: "平均客单",
          value: money(operatingMetrics.revenue.avg_order_value),
          hint: "按实收订单计算"
        },
        {
          label: "月营收投影",
          value: survival ? money(survival.projected_monthly_revenue) : "待计算",
          hint: survival ? `基于 ${survival.observed_days} 个营业日` : "需要成本分析"
        },
        {
          label: "月利润投影",
          value: survival ? money(survival.projected_monthly_profit) : "待计算",
          hint: survival ? `保本线 ${money(survival.break_even_monthly_revenue)}` : "需要成本分析",
          tone: survival
            ? survival.projected_monthly_profit >= 0 ? "positive" : "negative"
            : "default"
        },
        {
          label: "距离保本线",
          value: survival ? money(survival.monthly_revenue_gap) : "待计算",
          hint: survival && survival.monthly_revenue_gap >= 0 ? "高于保本要求" : "仍需补足营收",
          tone: survival
            ? survival.monthly_revenue_gap >= 0 ? "positive" : "warning"
            : "default"
        },
        {
          label: "现金可支撑",
          value: survival
            ? survival.cash_runway_months === null
              ? "已自我覆盖"
              : `${survival.cash_runway_months} 个月`
            : "待计算",
          hint: `${operatingMetrics.reviews.negative_review_count} 条中差评待处理`,
          tone: survival
            ? survival.risk_level === "high" ? "negative" : survival.risk_level === "watch" ? "warning" : "positive"
            : "default"
        }
      ]
    : Object.entries(report.metrics as Record<string, number>).map(([key, value]) => {
        const metric = presentMetric(key, value);
        return { label: metric.label, value: metric.value, hint: metric.source };
      });

  return (
    <div className="report-layout">
      <nav className="report-context-nav" aria-label="报告导航">
        <Link href={report.stage === "operating" ? "/operating#diagnosis" : "/pre-open#feasibility"}>
          <span aria-hidden="true">←</span>
          返回{report.stage === "operating" ? "经营诊断" : "开店测算"}
        </Link>
        <Link href="/">回到控制台</Link>
      </nav>
      <section className="report-overview">
        <div className="report-overview-copy">
          <div className="report-meta">
            <span>{report.stage === "operating" ? "经营中" : "开店前"}</span>
            <span>报告 #{report.analysis_id}</span>
          </div>
          <h1>{report.stage === "operating" ? "经营诊断" : "开店潜力测算"}</h1>
          <p>{report.summary}</p>
        </div>
        {survival ? (
          <aside className={`report-health report-health-${survival.risk_level}`} aria-label="当前经营状态">
            <span>当前经营状态</span>
            <strong>{HEALTH_LABELS[survival.risk_level]}</strong>
            <dl>
              <div><dt>月利润投影</dt><dd>{money(survival.projected_monthly_profit)}</dd></div>
              <div><dt>风险等级</dt><dd>{survival.risk_level === "high" ? "高" : survival.risk_level === "watch" ? "关注" : "稳定"}</dd></div>
            </dl>
          </aside>
        ) : null}
      </section>
      <MetricCards metrics={metricCards} />
      {agentTrace ? (
        <AgentRunStatus trace={agentTrace} analysisId={report.analysis_id} />
      ) : null}
      {operatingMetrics ? (
        <div className="report-analysis-grid">
          <div className="report-grid-revenue"><RevenueChart data={operatingMetrics.revenue.daily_revenue} /></div>
          {operatingMetrics.survival ? <div className="report-grid-survival"><SurvivalPanel metrics={operatingMetrics.survival} /></div> : null}
          {operatingMetrics.time_patterns ? <div className="report-grid-time"><TimePatternPanel metrics={operatingMetrics.time_patterns} /></div> : null}
          <div className="report-grid-menu-stack">
            <MenuMatrix items={operatingMetrics.menu.items} />
            <ReviewTopics topics={operatingMetrics.reviews.topics} />
          </div>
          {operatingMetrics.channels ? <div className="report-grid-wide"><ChannelProfitPanel metrics={operatingMetrics.channels} /></div> : null}
          {operatingMetrics.discounts ? <div className="report-grid-discount"><DiscountProfitPanel metrics={operatingMetrics.discounts} /></div> : null}
        </div>
      ) : null}
      <div className="report-columns">
        <RiskPanel risks={report.risks} />
        <EvidencePanel evidence={report.evidence} />
        <ActionList actions={report.actions} />
      </div>
      <AnalysisFollowup analysisId={report.analysis_id} stage={report.stage} />
    </div>
  );
}
