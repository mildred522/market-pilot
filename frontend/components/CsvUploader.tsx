"use client";

import { ChangeEvent, useState } from "react";
import Link from "next/link";
import { analyzeOperatingSample, createProject, uploadCsv } from "@/lib/api";
import type { UploadedFileResult } from "@/lib/types";

const fileTypes = [
  { id: "orders", label: "订单 CSV" },
  { id: "menu_items", label: "菜品成本 CSV" },
  { id: "reviews", label: "评论 CSV" }
];

export function CsvUploader() {
  const [projectName, setProjectName] = useState("已开面馆经营诊断");
  const [projectId, setProjectId] = useState<number | null>(null);
  const [uploads, setUploads] = useState<UploadedFileResult[]>([]);
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loadingType, setLoadingType] = useState<string | null>(null);

  async function ensureProject() {
    if (projectId) {
      return projectId;
    }
    const project = await createProject(projectName, "operating");
    setProjectId(project.id);
    return project.id;
  }

  async function handleFileChange(fileType: string, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    setError("");
    setLoadingType(fileType);
    try {
      const id = await ensureProject();
      const result = await uploadCsv(id, fileType, file);
      setUploads((current) => [...current.filter((item) => item.file_type !== fileType), result]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setLoadingType(null);
    }
  }

  async function handleSampleAnalyze() {
    setError("");
    setLoadingType("analysis");
    try {
      const id = await ensureProject();
      const report = await analyzeOperatingSample(id);
      setAnalysisId(report.analysis_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败");
    } finally {
      setLoadingType(null);
    }
  }

  return (
    <div className="workspace">
      <section className="form-surface">
        <label>
          项目名称
          <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
        </label>
        <div className="upload-list">
          {fileTypes.map((fileType) => (
            <label className="upload-row" key={fileType.id}>
              <span>{fileType.label}</span>
              <input
                accept=".csv"
                type="file"
                onChange={(event) => void handleFileChange(fileType.id, event)}
              />
              {loadingType === fileType.id ? <em>上传中...</em> : null}
            </label>
          ))}
        </div>
        <button disabled={loadingType !== null} onClick={() => void handleSampleAnalyze()} type="button">
          {loadingType === "analysis" ? "诊断中..." : "生成样例经营诊断"}
        </button>
      </section>

      <section className="result-surface" aria-live="polite">
        {error ? <p className="error-text">{error}</p> : null}
        <h2>上传状态</h2>
        {projectId ? <p>项目 ID：{projectId}</p> : <p className="muted-text">上传第一个文件时会自动创建项目。</p>}
        <ul>
          {uploads.map((upload) => (
            <li key={upload.file_type}>
              {upload.file_type}: {upload.filename}
            </li>
          ))}
        </ul>
        {analysisId ? (
          <Link className="inline-action" href={`/analysis/${analysisId}`}>
            查看完整报告
          </Link>
        ) : null}
        <p className="muted-text">经营诊断执行会在后续轮次接入字段映射和 Agent 报告。</p>
      </section>
    </div>
  );
}
