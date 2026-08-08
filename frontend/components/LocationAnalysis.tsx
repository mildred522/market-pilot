"use client";

import { FormEvent, useState } from "react";
import { AutocompleteField } from "@/components/AutocompleteField";
import { analyzeLocationManually, createProject, getLocationSuggestions, recommendLocations } from "@/lib/api";
import {
  ALL_DISTRICT_OPTIONS,
  CITY_OPTIONS,
  DISTRICTS_BY_CITY,
  normalizeCity,
  TARGET_CUSTOMER_OPTIONS
} from "@/lib/location-options";
import type { LocationResult } from "@/lib/types";

type Mode = "manual" | "recommendations";

const initial = {
  projectName: "成都茶饮商圈评估",
  city: "成都",
  district: "高新区",
  category: "奶茶",
  target_customer: "办公人群与周边社区居民",
  planned_average_order_value: 22,
  address: "",
  latitude: 30.5728,
  longitude: 104.0668,
  radius_meters: 1500,
  candidate_count: 5,
  monthly_rent: 20000,
  gross_margin: 0.65,
  labor_cost: 30000,
  utilities_cost: 5000,
  other_fixed_cost: 3000,
  target_daily_orders: 100
};

export function LocationAnalysis() {
  const [mode, setMode] = useState<Mode>("recommendations");
  const [form, setForm] = useState(initial);
  const [result, setResult] = useState<LocationResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const matchedCity = normalizeCity(form.city);
  const districtOptions = DISTRICTS_BY_CITY[matchedCity] ?? ALL_DISTRICT_OPTIONS;

  function update(name: keyof typeof initial, value: string | number) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function selectCity(city: string) {
    const districts = DISTRICTS_BY_CITY[normalizeCity(city)];
    setForm((current) => ({
      ...current,
      city,
      district: districts?.includes(current.district) ? current.district : (districts?.[0] ?? "")
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const project = await createProject(form.projectName, "pre_open");
      const finance_assumptions = {
        gross_margin: form.gross_margin,
        labor_cost: form.labor_cost,
        utilities_cost: form.utilities_cost,
        other_fixed_cost: form.other_fixed_cost,
        target_daily_orders: form.target_daily_orders,
        monthly_rent: form.monthly_rent
      };
      const common = {
        project_id: project.id,
        city: form.city,
        district: form.district,
        category: form.category,
        target_customer: form.target_customer,
        planned_average_order_value: form.planned_average_order_value,
        finance_assumptions,
        coordinate_system: "bd09ll" as const,
        radius_meters: form.radius_meters
      };
      const analysis = mode === "manual"
        ? await analyzeLocationManually({ ...common, latitude: form.latitude, longitude: form.longitude })
        : await recommendLocations({ ...common, candidate_count: form.candidate_count });
      setResult(analysis);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败");
    } finally {
      setLoading(false);
    }
  }

  function evaluateCandidate(candidate: LocationResult["candidates"][number]) {
    setMode("manual");
    setForm((current) => ({ ...current, latitude: candidate.transition_coordinates.latitude, longitude: candidate.transition_coordinates.longitude }));
    setResult(null);
  }

  return (
    <section className="location-workspace" id="location">
      <div className="location-intro">
        <div>
          <p className="kicker">Location intelligence</p>
          <h2>先看商圈，再评估铺位</h2>
          <p>百度 POI 只作为竞争、配套和交通的外部证据，不代表真实客流或营业额。</p>
        </div>
        <div className="mode-switch" role="tablist" aria-label="选址分析模式">
          <button className={mode === "recommendations" ? "active" : ""} onClick={() => setMode("recommendations")} type="button">自动推荐</button>
          <button className={mode === "manual" ? "active" : ""} onClick={() => setMode("manual")} type="button">手动选址</button>
        </div>
      </div>

      <div className="location-grid">
        <form className="form-surface" onSubmit={submit}>
          <label>项目名称<input value={form.projectName} onChange={(e) => update("projectName", e.target.value)} /></label>
          <div className="field-grid">
            <AutocompleteField label="城市" value={form.city} options={CITY_OPTIONS} onChange={(value) => update("city", value)} onSelect={selectCity} loadOptions={(query) => getLocationSuggestions("city", query)} placeholder="选择或输入城市" />
            <AutocompleteField key={`district-${form.city}`} label="行政区" value={form.district} options={districtOptions} onChange={(value) => update("district", value)} loadOptions={(query) => getLocationSuggestions("district", query, form.city)} minimumQueryLength={0} replaceOptionsWhenLoaded placeholder="选择或输入行政区" />
          </div>
          <div className="field-grid">
            <label>经营品类<input value={form.category} onChange={(e) => update("category", e.target.value)} /></label>
            <label>计划客单价<input type="number" value={form.planned_average_order_value} onChange={(e) => update("planned_average_order_value", Number(e.target.value))} /></label>
          </div>
          <AutocompleteField label="目标客群" value={form.target_customer} options={TARGET_CUSTOMER_OPTIONS} onChange={(value) => update("target_customer", value)} placeholder="选择或描述目标客群" />
          {mode === "manual" ? (
            <div className="field-grid">
              <label>BD-09 纬度<input type="number" step="0.000001" value={form.latitude} onChange={(e) => update("latitude", Number(e.target.value))} /></label>
              <label>BD-09 经度<input type="number" step="0.000001" value={form.longitude} onChange={(e) => update("longitude", Number(e.target.value))} /></label>
            </div>
          ) : null}
          <div className="field-grid">
            <label>分析半径（米）<input type="number" min="300" max="5000" value={form.radius_meters} onChange={(e) => update("radius_meters", Number(e.target.value))} /></label>
            {mode === "recommendations" ? <label>候选数量<input type="number" min="1" max="10" value={form.candidate_count} onChange={(e) => update("candidate_count", Number(e.target.value))} /></label> : <span />}
          </div>
          <details>
            <summary>财务假设</summary>
            <div className="field-grid compact-fields">
              <label>月租金<input type="number" value={form.monthly_rent} onChange={(e) => update("monthly_rent", Number(e.target.value))} /></label>
              <label>毛利率<input type="number" step="0.01" value={form.gross_margin} onChange={(e) => update("gross_margin", Number(e.target.value))} /></label>
              <label>人工成本<input type="number" value={form.labor_cost} onChange={(e) => update("labor_cost", Number(e.target.value))} /></label>
              <label>目标日订单<input type="number" value={form.target_daily_orders} onChange={(e) => update("target_daily_orders", Number(e.target.value))} /></label>
            </div>
          </details>
          <button disabled={loading} type="submit">{loading ? "分析中..." : mode === "manual" ? "分析这个点位" : "推荐候选商圈"}</button>
        </form>

        <LocationResultView result={result} error={error} onEvaluate={evaluateCandidate} />
      </div>
    </section>
  );
}

function LocationResultView({ result, error, onEvaluate }: { result: LocationResult | null; error: string; onEvaluate: (candidate: LocationResult["candidates"][number]) => void }) {
  if (error) return <section className="result-surface"><p className="error-text">{error}</p></section>;
  if (!result) return <section className="result-surface"><p className="muted-text">选择分析模式并提交条件，结果会显示在这里。</p></section>;
  if (result.mode === "recommendations") return <section className="result-surface"><div className="result-heading"><div><p className="kicker">Candidate areas</p><h2>候选商圈</h2></div><span className={`status-mark status-${result.status}`}>{result.status}</span></div><div className="candidate-list">{result.candidates.map((candidate) => <article className="candidate-row" key={`${candidate.name}-${candidate.center.latitude}`}><div><p className="candidate-rank">{candidate.name}</p><h3>{candidate.opportunity.score ?? "-"} <small>机会分</small></h3><p className="muted-text">可信度 {candidate.confidence.score ?? "-"} · {candidate.finance.feasibility ?? "未测算"}</p><p>{candidate.warnings[0] ?? candidate.recommendations[0]}</p></div><button type="button" onClick={() => onEvaluate(candidate)}>评估具体铺位</button></article>)}</div></section>;
  return <section className="result-surface"><div className="result-heading"><div><p className="kicker">Point analysis</p><h2>{result.opportunity.conclusion ?? "分析结果"}</h2></div><span className={`status-mark status-${result.status}`}>{result.status}</span></div><div className="location-metrics"><div><span>机会评分</span><strong>{result.opportunity.score ?? "-"}</strong></div><div><span>数据可信度</span><strong>{result.confidence.score ?? "-"}</strong></div><div><span>财务状态</span><strong>{result.finance.feasibility ?? "-"}</strong></div></div><h3>现场核验</h3><ul>{result.recommendations.map((item) => <li key={item}>{item}</li>)}</ul><h3>风险与警告</h3><ul>{[...result.risks, ...result.warnings].map((item) => <li key={item}>{item}</li>)}</ul></section>;
}
