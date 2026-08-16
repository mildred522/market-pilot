"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { askAnalysis, getAnswerVersions } from "@/lib/api";
import type { AnalysisFollowupResponse, AnswerVersion, FollowupSections } from "@/lib/types";

export function AnalysisFollowup({ analysisId }: { analysisId: number }) {
  const [question, setQuestion] = useState("");
  const [feedback, setFeedback] = useState("");
  const [revisionParentId, setRevisionParentId] = useState<number | null>(null);
  const [result, setResult] = useState<AnalysisFollowupResponse | null>(null);
  const [versions, setVersions] = useState<AnswerVersion[]>([]);
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
      setVersions(await getAnswerVersions(analysisId));
    } catch {
      setVersions([]);
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
              <strong>当前报告缺少这项事实</strong>
              <span>已保留可以确认的内容，没有用邻近指标代替。</span>
              {result.available_sections?.length ? (
                <small>当前已有：{result.available_sections.join("、")}</small>
              ) : null}
            </div>
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
  return (
    <div className="followup-answer-sections">
      {sections.data_findings.length ? (
        <section>
          <h3>基于门店数据</h3>
          <ul>{sections.data_findings.map((item, index) => <li key={`${item.text}-${index}`}>{item.text}</li>)}</ul>
        </section>
      ) : null}
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
