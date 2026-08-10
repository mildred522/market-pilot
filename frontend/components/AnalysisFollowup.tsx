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
        <p>最多读取三次已保存指标，不会修改数据或重新调用外部地图。</p>
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
          <div><strong>{result.mode === "llm" ? "AI 回答" : "确定性回退"}</strong><span>{result.steps} 轮 · 置信度 {(result.confidence * 100).toFixed(0)}%</span></div>
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
    step_limit: "Agent 轮次限制"
  };
  return labels[stage] ?? stage;
}

function friendlyFallbackReason(reason?: string): string {
  if (!reason) return "模型未生成可验证回答，已返回保存的报告结论。";
  if (reason.includes("not configured")) return "模型尚未配置，已返回保存的报告结论。";
  if (reason.includes("timed out") || reason.includes("network")) return "模型响应超时，已返回保存的报告结论。";
  if (reason.includes("reference") || reason.includes("evidence")) return "模型返回的证据引用未通过校验，已返回保存的报告结论。";
  if (reason.includes("maximum")) return "三轮只读分析后仍未形成答案，已返回保存的报告结论。";
  return "模型回答未通过安全校验，已返回保存的报告结论。";
}
