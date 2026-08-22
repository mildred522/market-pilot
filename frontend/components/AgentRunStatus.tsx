import type { AgentTrace } from "@/lib/types";
import { AgentRunDetails } from "@/components/AgentRunDetails";

const MODE_LABELS = {
  llm: "AI 规划与综合",
  hybrid: "AI + 规则降级",
  deterministic: "确定性分析"
};

const STATUS_LABELS = {
  degraded: "部分分析未完成",
  failed: "分析未完成"
};

export function AgentRunStatus({
  trace,
  analysisId
}: {
  trace: AgentTrace;
  analysisId: number;
}) {
  return (
    <div className={`agent-run-status agent-run-${trace.mode}`}>
      <div>
        <strong>{MODE_LABELS[trace.mode]}</strong>
        <span>{trace.model ?? trace.provider}</span>
        <span>{trace.selected_tools.length} 个分析工具</span>
        {trace.status && trace.status !== "completed" ? (
          <span>{STATUS_LABELS[trace.status]}</span>
        ) : null}
        {trace.run_id ? <span>运行 #{trace.run_id}</span> : null}
        <span>{trace.duration_ms} ms</span>
      </div>
      {trace.fallback_reasons.length > 0 ? (
        <details>
          <summary>查看降级信息</summary>
          <ul>
            {trace.fallback_reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </details>
      ) : null}
      <AgentRunDetails
        analysisId={analysisId}
        preferredRequestId={trace.request_id}
      />
    </div>
  );
}
