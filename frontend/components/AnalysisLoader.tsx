"use client";

import { useEffect, useState } from "react";
import { AgentReport } from "@/components/AgentReport";
import { getAnalysis } from "@/lib/api";
import type { AnalysisReport } from "@/lib/types";

export function AnalysisLoader({ analysisId }: { analysisId: number }) {
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getAnalysis(analysisId)
      .then(setReport)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "无法读取报告"));
  }, [analysisId]);

  if (error) return <main className="auth-loading" role="alert">{error}</main>;
  if (!report) return <main className="auth-loading" aria-live="polite">正在加载报告...</main>;
  return (
    <div className="report-page">
      <main className="shell report-shell"><AgentReport report={report} /></main>
    </div>
  );
}
