"use client";

import { useEffect, useState } from "react";
import { CommerceAgentWorkspace } from "@/components/CommerceAgentWorkspace";
import { getCommerceBenchmarkCategorySales, getCommerceBenchmarkHotProducts, getCommerceBenchmarkSales, getCommerceBenchmarkTrends, getCommerceBenchmarks, getCommerceComparisonWindows, getCommerceSelectionRecommendations } from "@/lib/api";
import type { CommerceBenchmarkSnapshotSummary, CommerceCategorySalesReport, CommerceComparisonWindows, CommerceHotProductReport, CommerceProductSalesReport, CommerceProductTrendReport, CommerceSelectionRecommendationReport } from "@/lib/types";

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

function shortProductId(productId: string): string {
  return productId.length > 12 ? `${productId.slice(0, 8)}…${productId.slice(-4)}` : productId;
}

function ProductReference({ productId, categoryName, showCategory = true }: { productId: string; categoryName: string | null; showCategory?: boolean }) {
  return (
    <>
      <strong>{showCategory ? categoryName ?? "未分类" : "商品"}</strong>
      <details className="commerce-product-id">
        <summary>ID：{shortProductId(productId)}</summary>
        <code>{productId}</code>
      </details>
    </>
  );
}

const hotLabelNames: Record<string, string> = {
  volume_leader: "销量领先",
  revenue_leader: "销售额领先",
  momentum: "增长动量",
  multi_seller: "多卖家覆盖"
};

const recommendationTypeNames: Record<string, string> = {
  verify_growth: "增长核验",
  validate_new_product: "新品验证",
  protect_winner: "保护头部",
  review_decline: "复核下降"
};

export default function CommercePage() {
  const [snapshots, setSnapshots] = useState<CommerceBenchmarkSnapshotSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [comparison, setComparison] = useState<CommerceComparisonWindows | null>(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [sales, setSales] = useState<CommerceProductSalesReport | null>(null);
  const [loadingSales, setLoadingSales] = useState(false);
  const [salesError, setSalesError] = useState("");
  const [categories, setCategories] = useState<CommerceCategorySalesReport | null>(null);
  const [loadingCategories, setLoadingCategories] = useState(false);
  const [categoriesError, setCategoriesError] = useState("");
  const [hotProducts, setHotProducts] = useState<CommerceHotProductReport | null>(null);
  const [loadingHotProducts, setLoadingHotProducts] = useState(false);
  const [hotProductsError, setHotProductsError] = useState("");
  const [trends, setTrends] = useState<CommerceProductTrendReport | null>(null);
  const [loadingTrends, setLoadingTrends] = useState(false);
  const [trendsError, setTrendsError] = useState("");
  const [recommendations, setRecommendations] = useState<CommerceSelectionRecommendationReport | null>(null);
  const [loadingRecommendations, setLoadingRecommendations] = useState(false);
  const [recommendationsError, setRecommendationsError] = useState("");

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
  const activeComparison = comparison?.snapshot_id === selectedId ? comparison : null;

  useEffect(() => {
    if (!selected || !salesSupported) {
      setComparison(null);
      setComparisonError("");
      setLoadingComparison(false);
      return;
    }
    let active = true;
    setComparison(null);
    setComparisonError("");
    setLoadingComparison(true);
    void getCommerceComparisonWindows(selected.snapshot_id)
      .then((windows) => {
        if (active) setComparison(windows);
      })
      .catch((caught) => {
        if (active) setComparisonError(caught instanceof Error ? caught.message : "分析窗口选择失败");
      })
      .finally(() => {
        if (active) setLoadingComparison(false);
      });
    return () => {
      active = false;
    };
  }, [selected, salesSupported]);

  useEffect(() => {
    if (!selected || !activeComparison) {
      setSales(null);
      setSalesError("");
      setLoadingSales(false);
      setCategories(null);
      setCategoriesError("");
      setLoadingCategories(false);
      return;
    }
    let active = true;
    setLoadingSales(true);
    setSalesError("");
    setSales(null);
    setLoadingCategories(true);
    setCategoriesError("");
    setCategories(null);
    const window = activeComparison.current_window;
    void getCommerceBenchmarkSales(selected.snapshot_id, window.start, window.end)
      .then((report) => {
        if (active) setSales(report);
      })
      .catch((caught) => {
        if (active) setSalesError(caught instanceof Error ? caught.message : "商品销售数据加载失败");
      })
      .finally(() => {
        if (active) setLoadingSales(false);
      });
    void getCommerceBenchmarkCategorySales(selected.snapshot_id, window.start, window.end)
      .then((report) => {
        if (active) setCategories(report);
      })
      .catch((caught) => {
        if (active) setCategoriesError(caught instanceof Error ? caught.message : "品类销售数据加载失败");
      })
      .finally(() => {
        if (active) setLoadingCategories(false);
      });
    return () => {
      active = false;
    };
  }, [selected, activeComparison]);

  useEffect(() => {
    if (!selected || !activeComparison) {
      setHotProducts(null);
      setHotProductsError("");
      setLoadingHotProducts(false);
      return;
    }
    let active = true;
    setLoadingHotProducts(true);
    setHotProductsError("");
    setHotProducts(null);
    const window = activeComparison.current_window;
    void getCommerceBenchmarkHotProducts(selected.snapshot_id, window.start, window.end)
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
  }, [selected, activeComparison]);

  useEffect(() => {
    if (!selected || !activeComparison) {
      setTrends(null);
      setTrendsError("");
      setLoadingTrends(false);
      setRecommendations(null);
      setRecommendationsError("");
      setLoadingRecommendations(false);
      return;
    }
    let active = true;
    const window = activeComparison.current_window;
    setLoadingTrends(true);
    setTrendsError("");
    setLoadingRecommendations(true);
    setRecommendationsError("");
    void getCommerceBenchmarkTrends(selected.snapshot_id, window.start, window.end)
      .then((report) => {
        if (active) setTrends(report);
      })
      .catch((caught) => {
        if (active) setTrendsError(caught instanceof Error ? caught.message : "商品趋势数据加载失败");
      })
      .finally(() => {
        if (active) setLoadingTrends(false);
      });
    void getCommerceSelectionRecommendations(selected.snapshot_id, window.start, window.end)
      .then((report) => {
        if (active) setRecommendations(report);
      })
      .catch((caught) => {
        if (active) setRecommendationsError(caught instanceof Error ? caught.message : "选品建议加载失败");
      })
      .finally(() => {
        if (active) setLoadingRecommendations(false);
      });
    return () => {
      active = false;
    };
  }, [selected, activeComparison]);

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
                {salesSupported ? (
                  <p className="commerce-history-notice">
                    Olist 是 2016–2018 年的历史公开平台样本，不是当前商家的实时数据。商品没有真实名称，页面以品类和商品 ID 标识；分析建议仅用于方法验证，不能直接用于当下采购或投放。
                  </p>
                ) : null}
                {salesSupported && loadingComparison ? <p className="commerce-empty">正在选择可比较的分析窗口...</p> : null}
                {salesSupported && comparisonError ? <p className="commerce-error" role="alert">{comparisonError}</p> : null}
                {activeComparison ? (
                  <p className="commerce-sales-note">
                    当前窗口 {formatDate(activeComparison.current_window.start)} — {formatDate(activeComparison.current_window.end)}（{activeComparison.current_order_count} 笔有效订单）；
                    基线窗口 {formatDate(activeComparison.baseline_window.start)} — {formatDate(activeComparison.baseline_window.end)}（{activeComparison.baseline_order_count} 笔有效订单）。
                    {activeComparison.warning ? ` ${activeComparison.warning}` : " 自动选取最近的密集等长 28 天窗口。"}
                  </p>
                ) : null}
                {activeComparison ? (
                  <CommerceAgentWorkspace
                    comparison={activeComparison}
                    key={`${selected.snapshot_id}:${activeComparison.current_window.start}`}
                    snapshotId={selected.snapshot_id}
                  />
                ) : null}
                <section className="commerce-sales-panel" aria-labelledby="commerce-categories-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Category sales</p>
                      <h2 id="commerce-categories-title">品类销售概览</h2>
                    </div>
                    <p>按当前窗口的成交订单商品行汇总；订单和卖家在每个品类内去重，跨品类不可直接相加。</p>
                  </div>
                  {activeComparison && loadingCategories ? <p className="commerce-empty">正在汇总品类销售...</p> : null}
                  {activeComparison && categoriesError ? <p className="commerce-error" role="alert">{categoriesError}</p> : null}
                  {activeComparison && !loadingCategories && !categoriesError && categories?.categories.length ? (
                    <div className="commerce-sales-table-wrap">
                      <table className="commerce-sales-table">
                        <thead><tr><th>品类</th><th>商品数</th><th>销量</th><th>订单数</th><th>销售额</th><th>卖家数</th></tr></thead>
                        <tbody>
                          {categories.categories.slice(0, 10).map((category) => (
                            <tr key={category.category_name ?? "__uncategorized__"}>
                              <td><strong>{category.category_name ?? "未分类"}</strong></td>
                              <td>{category.product_count}</td>
                              <td>{formatAmount(category.units_sold)}</td>
                              <td>{category.order_count}</td>
                              <td>{formatAmount(category.gross_amount)} {category.currency ?? ""}</td>
                              <td>{category.seller_count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="commerce-sales-note">展示销售额前 10 个品类，共 {categories.categories.length} 个；销售额不是利润，品类排行不代表未来需求。</p>
                    </div>
                  ) : null}
                  {activeComparison && !loadingCategories && !categoriesError && !categories?.categories.length ? <p className="commerce-empty">当前窗口没有可用的品类销售记录。</p> : null}
                </section>
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
                  {activeComparison && loadingSales ? <p className="commerce-empty">正在计算商品销售事实...</p> : null}
                  {activeComparison && salesError ? <p className="commerce-error" role="alert">{salesError}</p> : null}
                  {activeComparison && !loadingSales && !salesError && sales?.metrics.length ? (
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
                              <td><ProductReference productId={metric.product_id} categoryName={metric.category_name} showCategory={false} /></td>
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
                  {activeComparison && !loadingSales && !salesError && !sales?.metrics.length ? (
                    <p className="commerce-empty">当前窗口没有可用的成交商品销售记录。</p>
                  ) : null}
                </section>
                <section className="commerce-hot-panel" aria-labelledby="commerce-hot-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Explainable signals</p>
                      <h2 id="commerce-hot-title">热点商品候选</h2>
                    </div>
                    <p>热点是可解释候选；证据等级仅反映标签数量，不代表趋势预测、利润或因果关系。</p>
                  </div>
                  {activeComparison && loadingHotProducts ? <p className="commerce-empty">正在识别热点商品...</p> : null}
                  {activeComparison && hotProductsError ? <p className="commerce-error" role="alert">{hotProductsError}</p> : null}
                  {activeComparison && !loadingHotProducts && !hotProductsError && hotProducts?.candidates.length ? (
                    <div className="commerce-hot-list">
                      {hotProducts.candidates.map((candidate) => (
                        <article className="commerce-hot-card" key={candidate.item_id}>
                          <div className="commerce-hot-card-heading">
                            <div>
                              <span className="commerce-hot-rank">#{candidate.rank}</span>
                              <ProductReference productId={candidate.product_id} categoryName={candidate.category_name} />
                            </div>
                            <span className={`commerce-confidence commerce-confidence-${candidate.confidence}`}>
                              {candidate.confidence === "high" ? "高" : candidate.confidence === "medium" ? "中" : "低"}证据
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
                  {activeComparison && !loadingHotProducts && !hotProductsError && !hotProducts?.candidates.length ? (
                    <p className="commerce-empty">当前窗口没有满足可解释热点规则的商品。</p>
                  ) : null}
                </section>
                <section className="commerce-trend-panel" aria-labelledby="commerce-trend-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Window comparison</p>
                      <h2 id="commerce-trend-title">商品趋势</h2>
                    </div>
                    <p>与上方基线等长窗口比较；单侧出现的商品保留在结果中。</p>
                  </div>
                  {activeComparison && loadingTrends ? <p className="commerce-empty">正在计算商品趋势...</p> : null}
                  {activeComparison && trendsError ? <p className="commerce-error" role="alert">{trendsError}</p> : null}
                  {activeComparison && !loadingTrends && !trendsError && trends?.trends.length ? (
                    <div className="commerce-sales-table-wrap">
                      <table className="commerce-sales-table">
                        <thead><tr><th>商品</th><th>当前销售额</th><th>基线销售额</th><th>销售额变化</th><th>销量变化</th></tr></thead>
                        <tbody>
                          {[...trends.trends].sort((left, right) =>
                            Number(right.current?.gross_amount ?? 0) - Number(left.current?.gross_amount ?? 0) || left.item_id.localeCompare(right.item_id)
                          ).slice(0, 10).map((trend) => (
                            <tr key={trend.item_id}>
                              <td><ProductReference productId={trend.product_id} categoryName={trend.category_name} /></td>
                              <td>{formatAmount(trend.current?.gross_amount ?? null)}</td>
                              <td>{formatAmount(trend.previous?.gross_amount ?? null)}</td>
                              <td>{formatGrowth(trend.gross_amount_growth_rate)}</td>
                              <td>{formatGrowth(trend.units_growth_rate)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                  {activeComparison && !loadingTrends && !trendsError && !trends?.trends.length ? <p className="commerce-empty">当前没有可比较的商品趋势。</p> : null}
                </section>
                <section className="commerce-recommendation-panel" aria-labelledby="commerce-recommendation-title">
                  <div className="section-heading">
                    <div>
                      <p className="kicker">Evidence-based actions</p>
                      <h2 id="commerce-recommendation-title">选品与经营动作</h2>
                    </div>
                    <p>这些是待验证动作，不是利润结论，也不会自动执行。</p>
                  </div>
                  {activeComparison && loadingRecommendations ? <p className="commerce-empty">正在生成选品建议...</p> : null}
                  {activeComparison && recommendationsError ? <p className="commerce-error" role="alert">{recommendationsError}</p> : null}
                  {activeComparison && !loadingRecommendations && !recommendationsError && recommendations?.recommendations.length ? (
                    <div className="commerce-recommendation-list">
                      {recommendations.recommendations.map((recommendation) => (
                        <article className="commerce-recommendation-card" key={`${recommendation.item_id}-${recommendation.recommendation_type}`}>
                          <div className="commerce-hot-card-heading">
                            <div>
                              <span className="commerce-hot-rank">#{recommendation.rank}</span>
                              <strong>{recommendation.title.replace(recommendation.item_id, shortProductId(recommendation.item_id))}</strong>
                              <small>{recommendation.category_name ?? "未分类"}</small>
                              <details className="commerce-product-id">
                                <summary>查看完整商品 ID</summary>
                                <code>{recommendation.product_id}</code>
                              </details>
                            </div>
                            <span className={`commerce-confidence commerce-confidence-${recommendation.priority}`}>{recommendationTypeNames[recommendation.recommendation_type] ?? recommendation.recommendation_type}</span>
                          </div>
                          <p>{recommendation.action}</p>
                          <p className="commerce-recommendation-rationale">{recommendation.rationale}</p>
                          <div className="commerce-hot-labels">{recommendation.risk_flags.map((risk) => <span key={risk}>{risk}</span>)}</div>
                        </article>
                      ))}
                    </div>
                  ) : null}
                  {activeComparison && !loadingRecommendations && !recommendationsError && !recommendations?.recommendations.length ? <p className="commerce-empty">当前窗口没有足够证据生成选品动作。</p> : null}
                </section>
              </>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
