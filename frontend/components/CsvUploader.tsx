"use client";

import { ChangeEvent, useState } from "react";
import Link from "next/link";
import { ColumnMapper } from "@/components/ColumnMapper";
import { analyzeOperatingSample, analyzeOperatingUploads, createProject, uploadCsv } from "@/lib/api";
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
  const [mappings, setMappings] = useState<Record<string, Record<string, string>>>({});
  const [question, setQuestion] = useState("分析订单、菜品和差评，找出当前经营问题和整改重点");
  const [costs, setCosts] = useState({
    monthly_rent: 18000,
    monthly_labor: 24000,
    monthly_utilities: 3000,
    monthly_marketing: 2000,
    other_fixed_costs: 3000,
    cash_balance: 120000,
    delivery_commission_rate: 0.2,
    delivery_packaging_per_order: 1.5
  });
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
      setMappings((current) => ({ ...current, [fileType]: result.suggested_mapping }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setLoadingType(null);
    }
  }

  function updateMapping(fileType: string, standardField: string, sourceColumn: string) {
    setMappings((current) => ({
      ...current,
      [fileType]: { ...current[fileType], [standardField]: sourceColumn }
    }));
  }

  const requiredTypes = ["orders", "menu_items", "reviews"] as const;
  const readyForAnalysis = requiredTypes.every((fileType) => {
    const upload = uploads.find((item) => item.file_type === fileType);
    const mapping = mappings[fileType] ?? {};
    return upload?.required_columns.every((field) => Boolean(mapping[field]));
  });

  async function handleUploadedAnalyze() {
    if (!projectId || !readyForAnalysis) return;
    setError("");
    setLoadingType("analysis");
    try {
      const selections = Object.fromEntries(requiredTypes.map((fileType) => {
        const upload = uploads.find((item) => item.file_type === fileType)!;
        return [fileType, { file_id: upload.file_id, mapping: mappings[fileType] }];
      })) as Parameters<typeof analyzeOperatingUploads>[2];
      const report = await analyzeOperatingUploads(projectId, question, selections, costs);
      setAnalysisId(report.analysis_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败");
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
    <div className="workspace anchored-section" id="diagnosis">
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
        <label>
          诊断问题
          <input value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        <details>
          <summary>成本与现金假设</summary>
          <p className="form-help">用于计算保本线和现金压力，不会被当作真实财务流水。</p>
          <div className="field-grid compact-fields">
            {[
              ["monthly_rent", "月租金"],
              ["monthly_labor", "月人工"],
              ["monthly_utilities", "月水电杂费"],
              ["monthly_marketing", "月营销活动"],
              ["other_fixed_costs", "其他固定成本"],
              ["cash_balance", "可用现金余额"],
              ["delivery_commission_rate", "外卖佣金率（0-1）"],
              ["delivery_packaging_per_order", "外卖单均包材"]
            ].map(([field, label]) => (
              <label key={field}>
                {label}
                <input
                  min="0"
                  max={field === "delivery_commission_rate" ? "1" : undefined}
                  step={field === "delivery_commission_rate" ? "0.01" : "1"}
                  type="number"
                  value={costs[field as keyof typeof costs]}
                  onChange={(event) => setCosts((current) => ({
                    ...current,
                    [field]: Number(event.target.value)
                  }))}
                />
              </label>
            ))}
          </div>
        </details>
        <button disabled={loadingType !== null || !readyForAnalysis} onClick={() => void handleUploadedAnalyze()} type="button">
          {loadingType === "analysis" ? "诊断中..." : "分析已上传数据"}
        </button>
        <button className="secondary-action" disabled={loadingType !== null} onClick={() => void handleSampleAnalyze()} type="button">
          使用样例数据演示
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
        <p className="muted-text">上传三类数据并确认字段后，即可生成真实经营诊断。</p>
      </section>
      <ColumnMapper uploads={uploads} mappings={mappings} onChange={updateMapping} />
    </div>
  );
}
