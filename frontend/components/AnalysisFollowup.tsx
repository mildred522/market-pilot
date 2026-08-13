"use client";

import { FormEvent, useEffect, useState } from "react";
import { askAnalysis } from "@/lib/api";
import type { AnalysisFollowupResponse } from "@/lib/types";

export function AnalysisFollowup({ analysisId }: { analysisId: number }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnalysisFollowupResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!loading) return;
    setElapsedSeconds(0);
    const timer = window.setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      setResult(await askAnalysis(analysisId, question.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "追问失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="report-section followup-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Bounded ReAct</p>
          <h2>追问这份报告</h2>
        </div>
        <p>最多进行四轮只读分析，不会修改数据或重新调用外部地图。</p>
      </div>
      <form className="followup-form" onSubmit={submit}>
        <input
          maxLength={500}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：外卖贡献率为什么偏低？"
          value={question}
        />
        <button disabled={loading || !question.trim()} type="submit">
          {loading ? `分析中 ${elapsedSeconds}s` : "追问"}
        </button>
      </form>
      {loading ? (
        <p className="followup-progress" role="status">
          <i aria-hidden="true" />
          {elapsedSeconds < 10 ? "正在读取报告与指标…" : "模型仍在生成回答，复杂问题可能需要 10–30 秒。"}
        </p>
      ) : null}
      {error ? <p className="error-text">{error}</p> : null}
      {result ? (
        <div className="followup-answer" aria-live="polite">
          <div>
            <strong>{followupModeLabel(result.mode)}</strong>
            <span>
              {result.mode === "insufficient_data"
                ? `${result.steps} 轮 · 已核验数据范围`
                : `${result.steps} 轮 · 置信度 ${(result.confidence * 100).toFixed(0)}%`}
            </span>
          </div>
          <p>{result.answer}</p>
          {result.evidence_refs.length > 0 ? <small>依据：{result.evidence_refs.join("、")}</small> : null}
          {result.mode === "deterministic" ? (
            <div className="followup-fallback-note">
              <strong>已使用报告回退</strong>
              <span>{friendlyFallbackReason(result.fallback_reason)}</span>
              {result.supporting_evidence?.length ? (
                <ul>{result.supporting_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
              ) : null}
              {result.failure_detail ? (
                <details className="followup-failure-detail">
                  <summary>{result.failure_detail.candidate ? "查看模型候选回答与失败原因" : "查看失败诊断"}</summary>
                  <dl>
                    <div><dt>失败阶段</dt><dd>{failureStageLabel(result.failure_detail.stage)}</dd></div>
                    <div><dt>技术原因</dt><dd>{result.failure_detail.reason}</dd></div>
                  </dl>
                  {result.failure_detail.candidate ? (
                    <div className="followup-candidate">
                      <strong>未经验证的模型候选</strong>
                      <p>以下内容未通过结构或证据校验，仅用于排查，不应直接作为经营结论执行。</p>
                      <pre>{result.failure_detail.candidate}</pre>
                    </div>
                  ) : null}
                </details>
              ) : null}
            </div>
          ) : null}
          {result.mode === "insufficient_data" ? (
            <div className="followup-insufficient-note">
              <strong>当前报告缺少所需指标</strong>
              <span>系统没有用其他指标猜测答案。重新生成经营报告后，将自动纳入可用的渠道分析。</span>
              {result.available_sections?.length ? (
                <small>当前已有：{result.available_sections.join("、")}</small>
              ) : null}
              {result.failure_detail ? (
                <details className="followup-failure-detail">
                  <summary>查看数据可用性诊断</summary>
                  <dl>
                    <div><dt>诊断阶段</dt><dd>{failureStageLabel(result.failure_detail.stage)}</dd></div>
                    <div><dt>缺失指标</dt><dd>{result.missing_metrics?.join("、") || "未能确定具体指标"}</dd></div>
                    <div><dt>技术原因</dt><dd>{result.failure_detail.reason}</dd></div>
                  </dl>
                  {result.failure_detail.candidate ? (
                    <div className="followup-candidate">
                      <strong>模型最后一次请求</strong>
                      <p>该请求仅用于诊断，没有作为经营结论展示。</p>
                      <pre>{result.failure_detail.candidate}</pre>
                    </div>
                  ) : null}
                </details>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function failureStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    configuration: "模型配置",
    model_request: "模型请求",
    missing_content: "响应内容",
    non_text_content: "响应内容",
    invalid_json: "JSON 解析",
    schema_validation: "结构校验",
    answer_validation: "答案与证据校验",
    data_availability: "数据可用性",
    step_limit: "Agent 轮次限制"
  };
  return labels[stage] ?? stage;
}

function friendlyFallbackReason(reason?: string): string {
  if (!reason) return "模型未生成可验证回答，已返回保存的报告结论。";
  if (reason.includes("not configured")) return "模型尚未配置，已返回保存的报告结论。";
  if (reason.includes("timed out") || reason.includes("network")) return "模型响应超时，已返回保存的报告结论。";
  if (reason.includes("reference") || reason.includes("evidence")) return "模型返回的证据引用未通过校验，已返回保存的报告结论。";
  if (reason.includes("maximum")) return "四轮只读分析后仍未形成答案，已返回保存的报告结论。";
  return "模型回答未通过安全校验，已返回保存的报告结论。";
}

function followupModeLabel(mode: AnalysisFollowupResponse["mode"]): string {
  if (mode === "llm") return "AI 回答";
  if (mode === "insufficient_data") return "数据不足";
  return "确定性回退";
}
