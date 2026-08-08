import type { AgentTrace } from "@/lib/types";

const MODE_LABELS = {
  llm: "AI 规划与综合",
  hybrid: "AI + 规则降级",
  deterministic: "确定性分析"
};

export function AgentRunStatus({ trace }: { trace: AgentTrace }) {
  return (
    <div className={`agent-run-status agent-run-${trace.mode}`}>
      <div>
        <strong>{MODE_LABELS[trace.mode]}</strong>
        <span>{trace.model ?? trace.provider}</span>
        <span>{trace.selected_tools.length} 个分析工具</span>
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
    </div>
  );
}
