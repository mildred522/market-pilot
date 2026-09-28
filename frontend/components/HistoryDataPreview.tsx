import type { AnalysisReport } from "@/lib/types";
import { presentHistoryMetrics } from "@/lib/metric-presentation";

export function HistoryDataPreview({ report }: { report: AnalysisReport | null }) {
  if (!report) {
    return <section className="history-data-view"><p className="history-empty">选择一份报告查看保存的数据。</p></section>;
  }
  const metrics = presentHistoryMetrics(report.metrics as Record<string, unknown>);
  return (
    <section className="history-data-view" aria-label="报告数据视图">
      <div className="history-list-heading">
        <div>
          <p className="kicker">Saved data</p>
          <h2>数据视图</h2>
        </div>
        <span>报告 #{report.analysis_id}</span>
      </div>
      <p className="history-data-summary">{report.summary}</p>
      <dl className="history-metric-grid">
        {metrics.map((metric) => (
          <div key={metric.source}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
            <code>{metric.source}</code>
          </div>
        ))}
      </dl>
    </section>
  );
}
