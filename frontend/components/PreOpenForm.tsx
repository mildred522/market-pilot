"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { analyzePreOpen, createProject } from "@/lib/api";
import type { PreOpenReport } from "@/lib/types";

const initialForm = {
  projectName: "社区粉面店评估",
  category: "粉面",
  city: "成都",
  location_type: "community",
  area_sqm: 60,
  seats: 28,
  monthly_rent: 18000,
  total_investment: 280000,
  own_capital: 150000,
  debt_amount: 130000,
  expected_daily_orders: 90,
  expected_avg_order_value: 24,
  expected_gross_margin: 0.62,
  is_franchise: true,
  franchise_fee: 68000,
  competitor_count: 8,
  storefront_visibility: "medium"
};

export function PreOpenForm() {
  const [form, setForm] = useState(initialForm);
  const [report, setReport] = useState<PreOpenReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setReport(null);

    try {
      const project = await createProject(form.projectName, "pre_open");
      const result = await analyzePreOpen({
        project_id: project.id,
        category: form.category,
        city: form.city,
        location_type: form.location_type,
        area_sqm: form.area_sqm,
        seats: form.seats,
        monthly_rent: form.monthly_rent,
        total_investment: form.total_investment,
        own_capital: form.own_capital,
        debt_amount: form.debt_amount,
        expected_daily_orders: form.expected_daily_orders,
        expected_avg_order_value: form.expected_avg_order_value,
        expected_gross_margin: form.expected_gross_margin,
        is_franchise: form.is_franchise,
        franchise_fee: form.franchise_fee,
        competitor_count: form.competitor_count,
        storefront_visibility: form.storefront_visibility
      });
      setReport(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交失败");
    } finally {
      setLoading(false);
    }
  }

  function updateField(name: keyof typeof initialForm, value: string | number | boolean) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  return (
    <div className="workspace">
      <form className="form-surface" onSubmit={handleSubmit}>
        <label>
          项目名称
          <input
            value={form.projectName}
            onChange={(event) => updateField("projectName", event.target.value)}
          />
        </label>
        <label>
          品类
          <input value={form.category} onChange={(event) => updateField("category", event.target.value)} />
        </label>
        <label>
          城市
          <input value={form.city} onChange={(event) => updateField("city", event.target.value)} />
        </label>
        <label>
          月租金
          <input
            type="number"
            value={form.monthly_rent}
            onChange={(event) => updateField("monthly_rent", Number(event.target.value))}
          />
        </label>
        <label>
          总投资
          <input
            type="number"
            value={form.total_investment}
            onChange={(event) => updateField("total_investment", Number(event.target.value))}
          />
        </label>
        <label>
          预计日订单
          <input
            type="number"
            value={form.expected_daily_orders}
            onChange={(event) => updateField("expected_daily_orders", Number(event.target.value))}
          />
        </label>
        <label>
          预计客单价
          <input
            type="number"
            value={form.expected_avg_order_value}
            onChange={(event) => updateField("expected_avg_order_value", Number(event.target.value))}
          />
        </label>
        <label>
          预计毛利率
          <input
            type="number"
            step="0.01"
            value={form.expected_gross_margin}
            onChange={(event) => updateField("expected_gross_margin", Number(event.target.value))}
          />
        </label>
        <label>
          竞品数量
          <input
            type="number"
            value={form.competitor_count}
            onChange={(event) => updateField("competitor_count", Number(event.target.value))}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={form.is_franchise}
            onChange={(event) => updateField("is_franchise", event.target.checked)}
          />
          加盟项目
        </label>
        <button disabled={loading} type="submit">
          {loading ? "分析中..." : "生成潜力分析"}
        </button>
      </form>

      <section className="result-surface" aria-live="polite">
        {error ? <p className="error-text">{error}</p> : null}
        {report ? (
          <>
            <h2>分析结果</h2>
            <p>{report.summary}</p>
            <Link className="inline-action" href={`/analysis/${report.analysis_id}`}>
              查看完整报告
            </Link>
            <dl>
              {Object.entries(report.metrics).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <h3>风险</h3>
            <ul>{report.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
            <h3>行动</h3>
            <ul>{report.actions.map((action) => <li key={action}>{action}</li>)}</ul>
          </>
        ) : (
          <p className="muted-text">提交问卷后，这里会显示保本线、风险和行动建议。</p>
        )}
      </section>
    </div>
  );
}
