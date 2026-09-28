"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { HistoryDataPreview } from "@/components/HistoryDataPreview";
import { getAnalysis, getProjectAnalyses, getProjectHistory } from "@/lib/api";
import type { AnalysisHistoryItem, AnalysisReport, ProjectHistoryItem } from "@/lib/types";

export function HistoryWorkspace() {
  const [projects, setProjects] = useState<ProjectHistoryItem[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectHistoryItem | null>(null);
  const [analyses, setAnalyses] = useState<AnalysisHistoryItem[]>([]);
  const [activeAnalysisId, setActiveAnalysisId] = useState<number | null>(null);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [query, setQuery] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingAnalyses, setLoadingAnalyses] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadProjects();
  }, []);

  async function loadProjects(nextQuery = "") {
    setLoadingProjects(true);
    setError("");
    try {
      const response = await getProjectHistory(nextQuery);
      setProjects(response.items);
      const selected = response.items.find((item) => item.id === activeProject?.id)
        ?? response.items[0]
        ?? null;
      setActiveProject(selected);
      if (selected) await loadAnalyses(selected);
      else setAnalyses([]);
    } catch (caught) {
      setProjects([]);
      setAnalyses([]);
      setError(caught instanceof Error ? caught.message : "历史记录加载失败");
    } finally {
      setLoadingProjects(false);
    }
  }

  async function loadAnalyses(project: ProjectHistoryItem) {
    setLoadingAnalyses(true);
    try {
      const response = await getProjectAnalyses(project.id);
      setAnalyses(response.items);
      const selected = response.items.find((item) => item.id === activeAnalysisId)
        ?? response.items[0]
        ?? null;
      setActiveAnalysisId(selected?.id ?? null);
      if (selected) await loadReport(selected.id);
      else setReport(null);
    } catch (caught) {
      setAnalyses([]);
      setError(caught instanceof Error ? caught.message : "报告记录加载失败");
    } finally {
      setLoadingAnalyses(false);
    }
  }

  async function selectProject(project: ProjectHistoryItem) {
    setActiveProject(project);
    setError("");
    await loadAnalyses(project);
  }

  async function loadReport(analysisId: number) {
    try {
      setReport(await getAnalysis(analysisId));
    } catch (caught) {
      setReport(null);
      setError(caught instanceof Error ? caught.message : "报告数据加载失败");
    }
  }

  async function selectAnalysis(analysisId: number) {
    setActiveAnalysisId(analysisId);
    setError("");
    await loadReport(analysisId);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadProjects(query);
  }

  return (
    <main className="history-page">
      <div className="history-heading">
        <div>
          <p className="kicker">Workspace archive</p>
          <h1>历史记录</h1>
          <p>仅显示当前登录账号下的项目；打开已保存报告后可继续追问。</p>
        </div>
        <form className="history-search" onSubmit={submitSearch}>
          <input
            aria-label="搜索项目"
            maxLength={120}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目名称"
            value={query}
          />
          <button type="submit">搜索</button>
        </form>
      </div>

      {error ? <p className="history-error" role="alert">{error}</p> : null}

      <div className="history-layout">
        <section className="history-projects" aria-label="项目列表">
          <div className="history-list-heading">
            <h2>项目</h2>
            <span>{projects.length}</span>
          </div>
          {loadingProjects ? <p className="history-empty">正在读取项目...</p> : null}
          {!loadingProjects && !projects.length ? <p className="history-empty">还没有可恢复的项目。</p> : null}
          <ol>
            {projects.map((project) => (
              <li key={project.id}>
                <button
                  aria-pressed={activeProject?.id === project.id}
                  className={activeProject?.id === project.id ? "is-active" : ""}
                  onClick={() => void selectProject(project)}
                  type="button"
                >
                  <strong>{project.name}</strong>
                  <span>{stageLabel(project.stage)} · 更新于 {formatDate(project.updated_at)}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>

        <section className="history-analyses" aria-label="分析报告列表">
          <div className="history-list-heading">
            <div>
              <p className="kicker">Saved reports</p>
              <h2>{activeProject?.name ?? "选择一个项目"}</h2>
            </div>
            {activeProject ? <span>{analyses.length} 份报告</span> : null}
          </div>
          {loadingAnalyses ? <p className="history-empty">正在读取报告...</p> : null}
          {!loadingAnalyses && activeProject && !analyses.length ? <p className="history-empty">该项目尚未生成分析报告。</p> : null}
          <ol>
            {analyses.map((analysis) => (
              <li key={analysis.id}>
                <article>
                  <div>
                    <span className="history-stage">{stageLabel(analysis.stage)}</span>
                    <time dateTime={analysis.created_at}>{formatDate(analysis.created_at)}</time>
                  </div>
                  <p>{analysis.summary}</p>
                  <footer>
                    <span>{analysis.conversation_id ? "已保存追问记录" : "尚无追问记录"}</span>
                    <div>
                      <button
                        className={activeAnalysisId === analysis.id ? "is-active" : ""}
                        onClick={() => void selectAnalysis(analysis.id)}
                        type="button"
                      >
                        查看数据
                      </button>
                      <Link href={`/analysis/${analysis.id}`}>打开报告</Link>
                    </div>
                  </footer>
                </article>
              </li>
            ))}
          </ol>
        </section>
        <HistoryDataPreview report={report} />
      </div>
    </main>
  );
}

function stageLabel(stage: "pre_open" | "operating") {
  return stage === "operating" ? "经营诊断" : "开店测算";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
