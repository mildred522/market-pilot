"use client";

import { FormEvent, useState } from "react";
import { askAnalysis } from "@/lib/api";
import type { AnalysisFollowupResponse } from "@/lib/types";

export function AnalysisFollowup({ analysisId }: { analysisId: number }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnalysisFollowupResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError("");
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
          {loading ? "分析中…" : "追问"}
        </button>
      </form>
      {error ? <p className="error-text">{error}</p> : null}
      {result ? (
        <div className="followup-answer" aria-live="polite">
          <div><strong>{result.mode === "llm" ? "AI 回答" : "确定性回退"}</strong><span>{result.steps} 轮 · 置信度 {(result.confidence * 100).toFixed(0)}%</span></div>
          <p>{result.answer}</p>
          {result.evidence_refs.length > 0 ? <small>依据：{result.evidence_refs.join("、")}</small> : null}
        </div>
      ) : null}
    </section>
  );
}
