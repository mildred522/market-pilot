"use client";

import { useEffect, useState } from "react";
import { getCommerceBenchmarkHotProducts, getCommerceBenchmarkSales, getCommerceBenchmarks } from "@/lib/api";
import type { CommerceBenchmarkSnapshotSummary, CommerceHotProductReport, CommerceProductSalesReport } from "@/lib/types";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function formatPeriod(snapshot: CommerceBenchmarkSnapshotSummary): string {
  if (!snapshot.period_start || !snapshot.period_end) return "未提供时间范围";
  return `${formatDate(snapshot.period_start)} — ${formatDate(snapshot.period_end)}`;
}

function formatAmount(value: number | string | null): string {
  if (value === null) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatGrowth(value: number | string | null): string {
  if (value === null) return "—";
  const percentage = Number(value) * 100;
  return `${percentage >= 0 ? "+" : ""}${percentage.toFixed(1)}%`;
}

const hotLabelNames: Record<string, string> = {
  volume_leader: "销量领先",
  revenue_leader: "销售额领先",
  momentum: "增长动量",
  multi_seller: "多卖家覆盖"
};

export default function CommercePage() {
  const [snapshots, setSnapshots] = useState<CommerceBenchmarkSnapshotSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sales, setSales] = useState<CommerceProductSalesReport | null>(null);
  const [loadingSales, setLoadingSales] = useState(false);
  const [salesError, setSalesError] = useState("");
  const [hotProducts, setHotProducts] = useState<CommerceHotProductReport | null>(null);
  const [loadingHotProducts, setLoadingHotProducts] = useState(false);
  const [hotProductsError, setHotProductsError] = useState("");

  useEffect(() => {
    let active = true;
    void getCommerceBenchmarks()
      .then((items) => {
        if (!active) return;
        setSnapshots(items);
        setSelectedId(items[0]?.snapshot_id ?? "");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "电商数据加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const selected = snapshots.find((snapshot) => snapshot.snapshot_id === selectedId) ?? null;
  const salesSupported = selected?.schema_version === "olist-canonical-v2";

  useEffect(() => {
    if (!selected || !salesSupported) {
      setSales(null);
      setSalesError("");
      setLoadingSales(false);
      return;
    }
    let active = true;
    setLoadingSales(true);
    setSalesError("");
    setSales(null);
    const start = selected.period_start ?? selected.created_at;
    const periodEnd = selected.period_end ? new Date(selected.period_end) : new Date();
    periodEnd.setDate(periodEnd.getDate() + 1);
    void getCommerceBenchmarkSales(selected.snapshot_id, start, periodEnd.toISOString())
      .then((report) => {
        if (active) setSales(report);
      })
      .catch((caught) => {
        if (active) setSalesError(caught instanceof Error ? caught.message : "商品销售数据加载失败");
      })
      .finally(() => {
        if (active) setLoadingSales(false);
      });
    return () => {
      active = false;
    };
  }, [selected, selectedId, salesSupported]);

  useEffect(() => {
    if (!selected || !salesSupported) {
      setHotProducts(null);
      setHotProductsError("");
      setLoadingHotProducts(false);
      return;
    }
    let active = true;
    setLoadingHotProducts(true);
    setHotProductsError("");
    setHotProducts(null);
    const start = selected.period_start ?? selected.created_at;
    const periodEnd = selected.period_end ? new Date(selected.period_end) : new Date();
    periodEnd.setDate(periodEnd.getDate() + 1);
    void getCommerceBenchmarkHotProducts(selected.snapshot_id, start, periodEnd.toISOString())
      .then((report) => {
        if (active) setHotProducts(report);
      })
      .catch((caught) => {
        if (active) setHotProductsError(caught instanceof Error ? caught.message : "热点商品数据加载失败");
      })
      .finally(() => {
        if (active) setLoadingHotProducts(false);
      });
    return () => {
      active = false;
    };
  }, [selected, selectedId, salesSupported]);

  return (
    <main className="shell commerce-page">
      <section className="page-header">
        <p className="kicker">Commerce benchmark</p>
        <h1>电商经营分析</h1>
        <p>先选择一个经过本地校验的公开销售快照，再进入商品销售、热点商品和经营建议分析。</p>
      </section>

      {error ? <p className="commerce-error" role="alert">{error}</p> : null}

      <section className="commerce-snapshot-panel" aria-labelledby="commerce-snapshot-title">
        <div className="section-heading">
          <div>
            <p className="kicker">Data snapshot</p>
            <h2 id="commerce-snapshot-title">选择数据快照</h2>
          </div>
          <p>快照是共享的基准数据版本；这里只展示元数据，不返回订单或商品明细。</p>
        </div>

        {loading ? <p className="commerce-empty">正在读取本地基准数据...</p> : null}
        {!loading && !snapshots.length ? (
          <div className="commerce-empty">
            <strong>还没有可用的基准快照。</strong>
            <p>在后端项目根目录运行本地导入命令：</p>
            <code>python -m scripts.import_commerce_benchmark &lt;数据目录&gt;</code>
          </div>
        ) : null}

        {!loading && snapshots.length ? (
          <div className="commerce-snapshot-workspace">
            <label htmlFor="commerce-snapshot-select">基准快照</label>
            <select
              id="commerce-snapshot-select"
              onChange={(event) => setSelectedId(event.target.value)}
              value={selectedId}
            >
              {snapshots.map((snapshot) => (
                <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                  {snapshot.snapshot_id} · {formatDate(snapshot.created_at)}
                </option>
              ))}
            </select>

            {selected ? (
              <>
                <dl className="commerce-snapshot-details">
                <div><dt>数据来源</dt><dd>{selected.source_type}</dd></div>
                <div><dt>覆盖时间</dt><dd>{formatPeriod(selected)}</dd></div>
                <div><dt>结构版本</dt><dd>{selected.schema_version}</dd></div>
                <div><dt>能力</dt><dd>{selected.capabilities.join("、") || "未声明"}</dd></div>
                <div><dt>行数</dt><dd>{Object.entries(selected.row_counts).map(([key, value]) => `${key}: ${value}`).join(" · ")}</dd></div>
                <div><dt>内容指纹</dt><dd><code>{selected.content_hash}</code></dd></div>
                </dl>
                <section className="commerce-sales-panel" aria-labelledby="commerce-sales-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Product sales</p>
                      <h2 id="commerce-sales-title">商品销售排行</h2>
                    </div>
                    <p>当前只展示可由订单商品行直接支持的销量、销售额和卖家覆盖数。</p>
                  </div>
                  {!salesSupported ? (
                    <p className="commerce-empty">该快照尚未生成 Olist 商品销售事实层，请选择 `olist-canonical-v2` 快照。</p>
                  ) : null}
                  {salesSupported && loadingSales ? <p className="commerce-empty">正在计算商品销售事实...</p> : null}
                  {salesSupported && salesError ? <p className="commerce-error" role="alert">{salesError}</p> : null}
                  {salesSupported && !loadingSales && !salesError && sales?.metrics.length ? (
                    <div className="commerce-sales-table-wrap">
                      <table className="commerce-sales-table">
                        <thead>
                          <tr>
                            <th>商品</th>
                            <th>品类</th>
                            <th>销量</th>
                            <th>订单</th>
                            <th>销售额</th>
                            <th>卖家数</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sales.metrics.slice(0, 10).map((metric) => (
                            <tr key={metric.item_id}>
                              <td><strong>{metric.product_id}</strong><small>{metric.item_id}</small></td>
                              <td>{metric.category_name ?? "未分类"}</td>
                              <td>{formatAmount(metric.units_sold)}</td>
                              <td>{metric.order_count}</td>
                              <td>{formatAmount(metric.gross_amount)} {metric.currency ?? ""}</td>
                              <td>{metric.seller_count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="commerce-sales-note">纳入订单 {sales.included_order_count} 笔；排除订单 {sales.excluded_order_count} 笔。销售额不是利润。</p>
                    </div>
                  ) : null}
                  {salesSupported && !loadingSales && !salesError && !sales?.metrics.length ? (
                    <p className="commerce-empty">当前窗口没有可用的成交商品销售记录。</p>
                  ) : null}
                </section>
                <section className="commerce-hot-panel" aria-labelledby="commerce-hot-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Explainable signals</p>
                      <h2 id="commerce-hot-title">热点商品候选</h2>
                    </div>
                    <p>热点是可解释候选，不代表利润、因果关系或确定性选品结论。</p>
                  </div>
                  {salesSupported && loadingHotProducts ? <p className="commerce-empty">正在识别热点商品...</p> : null}
                  {salesSupported && hotProductsError ? <p className="commerce-error" role="alert">{hotProductsError}</p> : null}
                  {salesSupported && !loadingHotProducts && !hotProductsError && hotProducts?.candidates.length ? (
                    <div className="commerce-hot-list">
                      {hotProducts.candidates.map((candidate) => (
                        <article className="commerce-hot-card" key={candidate.item_id}>
                          <div className="commerce-hot-card-heading">
                            <div>
                              <span className="commerce-hot-rank">#{candidate.rank}</span>
                              <strong>{candidate.product_id}</strong>
                              <small>{candidate.category_name ?? "未分类"}</small>
                            </div>
                            <span className={`commerce-confidence commerce-confidence-${candidate.confidence}`}>
                              {candidate.confidence === "high" ? "高" : candidate.confidence === "medium" ? "中" : "低"}置信
                            </span>
                          </div>
                          <div className="commerce-hot-labels">
                            {candidate.labels.map((label) => <span key={label}>{hotLabelNames[label] ?? label}</span>)}
                          </div>
                          <p>{candidate.evidence.join("；")}</p>
                          <div className="commerce-hot-metrics">
                            <span>销量 {formatAmount(candidate.current.units_sold)}</span>
                            <span>销售额 {formatAmount(candidate.current.gross_amount)} {candidate.current.currency ?? ""}</span>
                            <span>基线增长 {formatGrowth(candidate.trend.gross_amount_growth_rate)}</span>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : null}
                  {salesSupported && !loadingHotProducts && !hotProductsError && !hotProducts?.candidates.length ? (
                    <p className="commerce-empty">当前窗口没有满足可解释热点规则的商品。</p>
                  ) : null}
                </section>
              </>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
