"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { askAnalysis, confirmCorrection, getAnswerVersions, getCorrections, rejectCorrection } from "@/lib/api";
import type { AnalysisFollowupResponse, AnswerVersion, CorrectionConfirmation, CorrectionProposal, FollowupSections } from "@/lib/types";

export function AnalysisFollowup({ analysisId }: { analysisId: number }) {
  const [question, setQuestion] = useState("");
  const [feedback, setFeedback] = useState("");
  const [revisionParentId, setRevisionParentId] = useState<number | null>(null);
  const [result, setResult] = useState<AnalysisFollowupResponse | null>(null);
  const [versions, setVersions] = useState<AnswerVersion[]>([]);
  const [corrections, setCorrections] = useState<CorrectionProposal[]>([]);
  const [correctionResults, setCorrectionResults] = useState<Record<number, CorrectionConfirmation>>({});
  const [correctionActionId, setCorrectionActionId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const feedbackRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void refreshVersions();
  }, [analysisId]);

  useEffect(() => {
    if (!loading) return;
    setElapsedSeconds(0);
    const timer = window.setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function refreshVersions() {
    try {
      const [nextVersions, nextCorrections] = await Promise.all([
        getAnswerVersions(analysisId),
        getCorrections(analysisId)
      ]);
      setVersions(nextVersions);
      setCorrections(nextCorrections);
    } catch {
      setVersions([]);
      setCorrections([]);
    }
  }

  async function applyCorrection(proposal: CorrectionProposal) {
    setCorrectionActionId(proposal.id);
    setError("");
    try {
      const confirmation = await confirmCorrection(proposal);
      setCorrectionResults((current) => ({ ...current, [proposal.id]: confirmation }));
      await refreshVersions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "经营事实更正失败");
    } finally {
      setCorrectionActionId(null);
    }
  }

  async function declineCorrection(proposal: CorrectionProposal) {
    setCorrectionActionId(proposal.id);
    setError("");
    try {
      await rejectCorrection(proposal.id);
      await refreshVersions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "拒绝更正失败");
    } finally {
      setCorrectionActionId(null);
    }
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    await runRequest(() => askAnalysis(analysisId, question.trim()));
    setQuestion("");
  }

  async function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parentVersionId = revisionParentId ?? result?.answer_version_id;
    if (!feedback.trim() || !parentVersionId) return;
    await runRequest(() => askAnalysis(analysisId, {
      parentVersionId,
      feedback: feedback.trim()
    }));
    setFeedback("");
    setRevisionParentId(null);
  }

  async function runRequest(request: () => Promise<AnalysisFollowupResponse>) {
    setLoading(true);
    setError("");
    try {
      const next = await request();
      setResult(next);
      await refreshVersions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "追问失败");
    } finally {
      setLoading(false);
    }
  }

  function reviseVersion(versionId: number) {
    setRevisionParentId(versionId);
    window.setTimeout(() => feedbackRef.current?.focus(), 0);
  }

  const activeParentId = revisionParentId ?? result?.answer_version_id ?? null;

  return (
    <section className="report-section followup-section">
      <div className="section-heading">
        <div>
          <p className="kicker">经营顾问</p>
          <h2>追问这份报告</h2>
        </div>
        <p>结合门店数据回答；需要历史或外部资料时会单独核验。</p>
      </div>

      <form className="followup-form" onSubmit={submitQuestion}>
        <input
          aria-label="追问内容"
          maxLength={500}
          name="question"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：根据现有表现，哪些菜品值得主推？"
          value={question}
        />
        <button disabled={loading || !question.trim()} type="submit">
          {loading ? `分析中 ${elapsedSeconds}s` : "追问"}
        </button>
      </form>

      {loading ? (
        <p className="followup-progress" role="status">
          <i aria-hidden="true" />
          {elapsedSeconds < 10 ? "正在核对报告证据…" : "正在补充分析，请稍候。"}
        </p>
      ) : null}
      {error ? <p className="error-text">{error}</p> : null}

      {result ? (
        <div className="followup-answer" aria-live="polite">
          <div className="followup-answer-meta">
            <strong>{followupModeLabel(result.mode)}</strong>
            <span>{followupStatus(result)}</span>
          </div>

          {hasSections(result.sections) ? (
            <AnswerSections sections={result.sections} />
          ) : (
            <p>{result.answer}</p>
          )}

          {result.evidence_refs.length > 0 ? (
            <details className="followup-evidence-refs">
              <summary>查看引用的数据项</summary>
              <ul>{result.evidence_refs.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}

          {result.mode === "deterministic" ? (
            <div className="followup-fallback-note">
              <strong>已使用报告中的确定数据回答</strong>
              <span>{friendlyFallbackReason(result.fallback_reason)}</span>
            </div>
          ) : null}

          {result.mode === "insufficient_data" ? (
            <div className="followup-insufficient-note">
              <strong>{result.missing_evidence?.length ? "当前项目缺少外部证据" : "当前报告缺少这项事实"}</strong>
              <span>{insufficientGuidance(result)}</span>
              {result.available_sections?.length ? (
                <small>当前已有：{result.available_sections.join("、")}</small>
              ) : null}
            </div>
          ) : null}

          {result.agent_trace?.evidence_events?.length ? (
            <details className="followup-evidence-refs">
              <summary>查看证据核验记录</summary>
              <ul>
                {result.agent_trace.evidence_events.map((event, index) => (
                  <li key={`${event.capability}-${index}`}>
                    {evidenceCapabilityLabel(event.capability)}：
                    {event.status === "completed" ? `已取得 ${event.evidence_refs.length} 项证据` : "未取得可用证据"}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {activeParentId ? (
            <form className="followup-revision-form" onSubmit={submitRevision}>
              <label htmlFor="followup-feedback">
                修改这版回答
                {revisionParentId ? <span>基于版本 #{revisionParentId}</span> : null}
              </label>
              <div>
                <input
                  id="followup-feedback"
                  maxLength={1000}
                  name="feedback"
                  onChange={(event) => setFeedback(event.target.value)}
                  placeholder="例如：简短一点，先给结论；或再结合成都趋势"
                  ref={feedbackRef}
                  value={feedback}
                />
                <button disabled={loading || !feedback.trim()} type="submit">生成新版本</button>
              </div>
            </form>
          ) : null}
        </div>
      ) : null}

      {corrections.length ? (
        <section className="correction-workflow" aria-label="经营事实更正">
          <div className="correction-heading">
            <div>
              <p className="kicker">Human-in-the-loop</p>
              <h3>经营事实更正</h3>
            </div>
            <span>确认后生成新报告，旧报告不会被覆盖</span>
          </div>
          <ul>
            {corrections.map((proposal) => {
              const confirmation = correctionResults[proposal.id];
              return (
                <li key={proposal.id}>
                  <div className="correction-diff">
                    <strong>{correctionFieldLabel(proposal.field)}</strong>
                    <span>{formatCorrectionValue(proposal.field, proposal.old_value)}</span>
                    <b aria-label="变更为">→</b>
                    <span>{formatCorrectionValue(proposal.field, proposal.new_value)}</span>
                  </div>
                  <p>{proposal.reason}</p>
                  {proposal.status === "pending" ? (
                    <div className="correction-actions">
                      <button
                        disabled={correctionActionId === proposal.id}
                        onClick={() => void applyCorrection(proposal)}
                        type="button"
                      >
                        {correctionActionId === proposal.id ? "处理中" : "确认并重算"}
                      </button>
                      <button
                        className="secondary-button"
                        disabled={correctionActionId === proposal.id}
                        onClick={() => void declineCorrection(proposal)}
                        type="button"
                      >
                        拒绝
                      </button>
                    </div>
                    ) : proposal.status === "applying" ? (
                      <span className="correction-pending">正在重算，请稍候</span>
                    ) : proposal.status === "applied" && proposal.applied_analysis_id ? (
                    <div className="correction-outcome">
                      <span>已确认并生成报告 #{proposal.applied_analysis_id}</span>
                      <Link href={`/analysis/${proposal.applied_analysis_id}`}>查看新报告</Link>
                      {confirmation ? <small>共更新 {confirmation.metric_changes.length} 项指标</small> : null}
                    </div>
                  ) : (
                    <span className="correction-rejected">已拒绝，未修改任何数据</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {versions.length ? (
        <details className="followup-version-history">
          <summary>回答版本（{versions.length}）</summary>
          <ol>
            {[...versions].reverse().map((version) => (
              <li key={version.id}>
                <div>
                  <strong>版本 #{version.id}</strong>
                  <span>{versionLabel(version.revision_type)} · {formatDate(version.created_at)}</span>
                </div>
                <p>{version.user_feedback || version.original_question}</p>
                <button onClick={() => reviseVersion(version.id)} type="button">基于此版本修改</button>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}

function AnswerSections({ sections }: { sections: FollowupSections }) {
  const findingGroups = [
    ["current_report", "基于门店数据"],
    ["external", "外部行业证据"],
    ["history", "历史经营数据"],
    ["reference", "目标与参考基准"],
    ["mixed", "综合证据"],
  ] as const;
  return (
    <div className="followup-answer-sections">
      {findingGroups.map(([scope, title]) => {
        const findings = sections.data_findings.filter(
          (item) => (item.scope ?? "current_report") === scope,
        );
        return findings.length ? (
          <section key={scope}>
            <h3>{title}</h3>
            <ul>{findings.map((item, index) => <li key={`${item.text}-${index}`}>{item.text}</li>)}</ul>
          </section>
        ) : null;
      })}
      {sections.general_advice.length ? (
        <section>
          <h3>通用经营建议</h3>
          <ul>{sections.general_advice.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
        </section>
      ) : null}
      {sections.missing_information.length ? (
        <section className="followup-missing-section">
          <h3>当前缺少的信息</h3>
          <ul>{sections.missing_information.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
        </section>
      ) : null}
    </div>
  );
}

function hasSections(sections?: FollowupSections): sections is FollowupSections {
  return Boolean(sections && (
    sections.data_findings.length
    || sections.general_advice.length
    || sections.missing_information.length
  ));
}

function followupStatus(result: AnalysisFollowupResponse): string {
  if (result.mode === "confirmation_required") return "等待确认经营事实";
  if (result.mode === "insufficient_data") return `${result.steps} 轮 · 已核验数据范围`;
  const labels: Record<string, string> = {
    complete: "回答完整",
    repaired: "已局部修正",
    partial: "已保留可信部分"
  };
  return `${result.steps} 轮 · ${labels[result.quality ?? ""] ?? `置信度 ${(result.confidence * 100).toFixed(0)}%`}`;
}

function friendlyFallbackReason(reason?: string): string {
  if (!reason) return "模型未生成可验证回答，已返回保存的报告结论。";
  if (reason.includes("not configured")) return "模型尚未配置，已返回保存的报告结论。";
  if (reason.includes("timed out") || reason.includes("network")) return "模型响应超时，已返回保存的报告结论。";
  return "模型回答未通过证据校验，已返回报告中能够确认的内容。";
}

function insufficientGuidance(result: AnalysisFollowupResponse): string {
  if (result.missing_evidence?.includes("location_competitors")) {
    return "需要先完成商圈或选址分析，保存周边竞品快照后才能比较具体门店。";
  }
  if (result.missing_evidence?.includes("external_industry_context")) {
    return "需要先接入或更新行业与城市资料，不能用门店指标代替市场证据。";
  }
  if (result.missing_evidence?.includes("metric_history")) {
    return "需要至少两期经营报告，当前单期数据无法判断历史变化。";
  }
  return "已保留可以确认的内容，没有用邻近指标代替。";
}

function evidenceCapabilityLabel(
  capability: "metric_history" | "external_industry_context" | "location_competitors",
): string {
  const labels = {
    metric_history: "历史经营数据",
    external_industry_context: "行业与城市资料",
    location_competitors: "周边竞品快照",
  };
  return labels[capability];
}

function followupModeLabel(mode: AnalysisFollowupResponse["mode"]): string {
  if (mode === "llm") return "经营分析";
  if (mode === "insufficient_data") return "数据不足";
  if (mode === "confirmation_required") return "待确认";
  return "报告数据回答";
}

function versionLabel(revisionType: string): string {
  const labels: Record<string, string> = {
    initial: "初始回答",
    rewrite_only: "表达调整",
    recompose_with_existing_evidence: "基于原证据重组",
    retrieve_more_evidence: "补充证据",
    recompute_metrics: "事实更正"
  };
  return labels[revisionType] ?? "回答修订";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function correctionFieldLabel(field: CorrectionProposal["field"]): string {
  const labels: Record<CorrectionProposal["field"], string> = {
    monthly_rent: "月租",
    monthly_labor: "人工成本",
    monthly_utilities: "水电成本",
    monthly_marketing: "营销费用",
    other_fixed_costs: "其他固定成本",
    cash_balance: "现金余额",
    delivery_commission_rate: "外卖佣金率",
    delivery_packaging_per_order: "单均包材成本"
  };
  return labels[field];
}

function formatCorrectionValue(field: CorrectionProposal["field"], value: number): string {
  if (field === "delivery_commission_rate") {
    return `${(value * 100).toFixed(1)}%`;
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}
