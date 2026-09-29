"use client";

import { useEffect, useState } from "react";
import { getCommerceBenchmarks } from "@/lib/api";
import type { CommerceBenchmarkSnapshotSummary } from "@/lib/types";

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

export default function CommercePage() {
  const [snapshots, setSnapshots] = useState<CommerceBenchmarkSnapshotSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
              <dl className="commerce-snapshot-details">
                <div><dt>数据来源</dt><dd>{selected.source_type}</dd></div>
                <div><dt>覆盖时间</dt><dd>{formatPeriod(selected)}</dd></div>
                <div><dt>结构版本</dt><dd>{selected.schema_version}</dd></div>
                <div><dt>能力</dt><dd>{selected.capabilities.join("、") || "未声明"}</dd></div>
                <div><dt>行数</dt><dd>{Object.entries(selected.row_counts).map(([key, value]) => `${key}: ${value}`).join(" · ")}</dd></div>
                <div><dt>内容指纹</dt><dd><code>{selected.content_hash}</code></dd></div>
              </dl>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
