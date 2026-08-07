import { ActionList } from "@/components/ActionList";
import { EvidencePanel } from "@/components/EvidencePanel";
import { MenuMatrix } from "@/components/MenuMatrix";
import { MetricCards } from "@/components/MetricCards";
import { RevenueChart } from "@/components/RevenueChart";
import { ReviewTopics } from "@/components/ReviewTopics";
import { RiskPanel } from "@/components/RiskPanel";
import type { AnalysisReport, OperatingMetrics } from "@/lib/types";

function isOperatingMetrics(metrics: AnalysisReport["metrics"]): metrics is OperatingMetrics {
  return "revenue" in metrics && "menu" in metrics && "reviews" in metrics;
}

export function AgentReport({ report }: { report: AnalysisReport }) {
  const isOperating = report.stage === "operating" && isOperatingMetrics(report.metrics);
  const operatingMetrics: OperatingMetrics | null = isOperating
    ? (report.metrics as OperatingMetrics)
    : null;
  const metricCards = operatingMetrics
    ? [
        { label: "总营收", value: operatingMetrics.revenue.total_revenue },
        { label: "订单数", value: operatingMetrics.revenue.order_count },
        { label: "客单价", value: operatingMetrics.revenue.avg_order_value },
        { label: "中差评", value: operatingMetrics.reviews.negative_review_count }
      ]
    : Object.entries(report.metrics as Record<string, number>).map(([key, value]) => ({
        label: key,
        value
      }));

  return (
    <div className="report-layout">
      <section className="report-hero">
        <p className="kicker">{report.stage === "operating" ? "Operating report" : "Pre-open report"}</p>
        <h1>{report.stage === "operating" ? "经营诊断报告" : "开店潜力报告"}</h1>
        <p>{report.summary}</p>
      </section>
      <MetricCards metrics={metricCards} />
      {operatingMetrics ? (
        <>
          <RevenueChart data={operatingMetrics.revenue.daily_revenue} />
          <MenuMatrix items={operatingMetrics.menu.items} />
          <ReviewTopics topics={operatingMetrics.reviews.topics} />
        </>
      ) : null}
      <div className="report-columns">
        <RiskPanel risks={report.risks} />
        <EvidencePanel evidence={report.evidence} />
        <ActionList actions={report.actions} />
      </div>
    </div>
  );
}
