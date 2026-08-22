"use client";

import { useState } from "react";
import { getAgentRun, getAgentRuns } from "@/lib/api";
import type { AgentRunDetail, AgentRunSummary } from "@/lib/types";

const OPERATION_LABELS = {
  operating_analysis: "经营报告",
  followup: "报告追问"
};

const STATUS_LABELS = {
  completed: "完成",
  degraded: "降级完成",
  failed: "失败"
};

export function AgentRunDetails({
  analysisId,
  preferredRequestId
}: {
  analysisId: number;
  preferredRequestId?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [detail, setDetail] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (runs.length || loading) return;
    setLoading(true);
    setError("");
    try {
      const available = await getAgentRuns(analysisId);
      setRuns(available);
      const selected = available.find((run) => run.request_id === preferredRequestId)
        ?? available.at(-1);
      if (selected) setDetail(await getAgentRun(analysisId, selected.request_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取运行详情");
    } finally {
      setLoading(false);
    }
  }

  async function selectRun(run: AgentRunSummary) {
    if (run.request_id === detail?.request_id || loading) return;
    setLoading(true);
    setError("");
    try {
      setDetail(await getAgentRun(analysisId, run.request_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取运行详情");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="agent-run-explorer">
      <button
        type="button"
        className="agent-run-toggle"
        aria-expanded={expanded}
        onClick={toggle}
      >
        {expanded ? "收起运行详情" : "查看运行详情"}
      </button>
      {expanded ? (
        <section className="agent-run-details" aria-label="Agent 运行详情">
          {runs.length > 1 ? (
            <div className="agent-run-selector" role="tablist" aria-label="选择运行">
              {runs.map((run) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={run.request_id === detail?.request_id}
                  className={run.request_id === detail?.request_id ? "active" : ""}
                  key={run.request_id}
                  onClick={() => selectRun(run)}
                >
                  <strong>{OPERATION_LABELS[run.operation]}</strong>
                  <span>{formatTime(run.created_at)}</span>
                </button>
              ))}
            </div>
          ) : null}
          {loading && !detail ? <p className="agent-run-message">正在读取运行记录...</p> : null}
          {error ? <p className="agent-run-message error-text">{error}</p> : null}
          {!loading && !error && runs.length === 0 ? (
            <p className="agent-run-message">当前分析没有可复盘的运行记录。</p>
          ) : null}
          {detail ? <RunDetail detail={detail} updating={loading} /> : null}
        </section>
      ) : null}
    </div>
  );
}

function RunDetail({ detail, updating }: { detail: AgentRunDetail; updating: boolean }) {
  return (
    <div className={updating ? "agent-run-content is-updating" : "agent-run-content"}>
      <header className="agent-run-detail-heading">
        <div>
          <p className="kicker">Agent run</p>
          <h2>{OPERATION_LABELS[detail.operation]}</h2>
        </div>
        <span className={`agent-run-outcome outcome-${detail.status}`}>
          {STATUS_LABELS[detail.status]}
        </span>
      </header>
      <dl className="agent-run-metrics">
        <Metric label="总耗时" value={formatDuration(detail.duration_ms)} />
        <Metric label="模型调用" value={`${detail.usage.model_calls} 次`} />
        <Metric label="工具调用" value={`${detail.usage.tool_calls} 次`} />
        <Metric
          label="Token"
          value={detail.usage.total_tokens === null
            ? "供应商未返回"
            : detail.usage.total_tokens.toLocaleString("zh-CN")}
        />
        <Metric label="Replan" value={`${detail.usage.replan_count} 次`} />
        <Metric label="校验" value={detail.verification.passed ? "通过" : `${detail.verification.failure_count} 项异常`} />
      </dl>
      <div className="agent-run-budget">
        <span>执行预算</span>
        <strong>{budgetStatus(detail)}</strong>
        {Object.keys(detail.budget.used).length ? (
          <p>
            模型 {detail.budget.used.model_calls ?? 0}/{detail.budget.limits.max_model_calls ?? "-"}
            {" · "}检索 {detail.budget.used.external_retrievals ?? 0}/{detail.budget.limits.max_external_retrievals ?? "-"}
            {" · "}重规划 {detail.budget.used.replans ?? 0}/{detail.budget.limits.max_replans ?? "-"}
          </p>
        ) : null}
      </div>
      <div className="agent-run-plan">
        <span>计划目标</span>
        <strong>{detail.initial_plan.goal || detail.initial_plan.intent}</strong>
        {detail.initial_plan.workflow ? (
          <p>
            工作流 {detail.initial_plan.workflow}
            {detail.initial_plan.dimensions.length
              ? ` · 维度 ${detail.initial_plan.dimensions.join(" / ")}`
              : ""}
          </p>
        ) : null}
        <p>{detail.initial_plan.tools.length
          ? detail.initial_plan.tools.join(" / ")
          : "当前运行无需确定性分析工具"}</p>
        {detail.planning_disclosure.reduction_percent !== undefined ? (
          <small>
            Planner 目录压缩 {detail.planning_disclosure.reduction_percent}%
            {detail.planning_disclosure.candidate_workflow_count !== undefined
              ? ` · 披露 ${detail.planning_disclosure.candidate_workflow_count} 个候选工作流`
              : ""}
          </small>
        ) : null}
      </div>
      <div className="agent-run-timeline-heading">
        <h3>执行阶段</h3>
        <span>逻辑视图</span>
      </div>
      <ol className="agent-run-timeline">
        {detail.timeline.map((stage, index) => (
          <li className={`stage-${stage.status}`} key={`${stage.stage}-${index}`}>
            <span className="agent-run-stage-index">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{stage.label}</strong>
              <p>{stage.public_detail}</p>
              <small>
                {[stage.model, formatOptionalDuration(stage.duration_ms), formatOptionalTokens(stage.total_tokens)]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </div>
            <span>{STATUS_LABELS[stage.status]}</span>
          </li>
        ))}
      </ol>
      {detail.fallback_reasons.length ? (
        <details className="agent-run-fallbacks">
          <summary>查看降级原因</summary>
          <ul>{detail.fallback_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </details>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatDuration(milliseconds: number) {
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(1)} 秒` : `${milliseconds} ms`;
}

function formatOptionalDuration(milliseconds: number | null) {
  return milliseconds === null ? "" : formatDuration(milliseconds);
}

function formatOptionalTokens(tokens: number | null) {
  return tokens === null ? "" : `${tokens.toLocaleString("zh-CN")} tokens`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function budgetStatus(detail: AgentRunDetail) {
  if (!Object.keys(detail.budget.limits).length) return "历史记录未采集";
  if (detail.budget.exhausted_dimensions.length) {
    return `已停止：${detail.budget.exhausted_dimensions.join(" / ")}`;
  }
  return detail.budget.evidence_truncated ? "正常，证据已压缩" : "正常";
}
