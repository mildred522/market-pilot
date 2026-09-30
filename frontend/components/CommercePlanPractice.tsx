"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { createCommercePlanPractice, getCommercePlanPractice } from "@/lib/api";
import type { CommercePlanPracticeRecord, CommercePlanResponse } from "@/lib/types";

function formatTimestamp(value: string): string {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Date(normalized).toLocaleString("zh-CN");
}

export function CommercePlanPractice({ plan }: { plan: CommercePlanResponse }) {
  const [records, setRecords] = useState<CommercePlanPracticeRecord[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [kind, setKind] = useState<"scenario" | "reflection">("scenario");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    void loadRecords();
    return () => {
      requestId.current += 1;
    };
  }, [plan.id]);

  async function loadRecords() {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const page = await getCommercePlanPractice(plan.id);
      if (currentRequest !== requestId.current) return;
      setRecords(page.items);
      setNextOffset(page.next_offset);
    } catch (caught) {
      if (currentRequest === requestId.current) setError(caught instanceof Error ? caught.message : "演练记录加载失败");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  async function loadMore() {
    if (nextOffset === null || loading || saving) return;
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const page = await getCommercePlanPractice(plan.id, nextOffset);
      if (currentRequest !== requestId.current) return;
      setRecords((items) => [...items, ...page.items.filter((item) => !items.some((current) => current.id === item.id))]);
      setNextOffset(page.next_offset);
    } catch (caught) {
      if (currentRequest === requestId.current) setError(caught instanceof Error ? caught.message : "更早的演练记录加载失败");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!note.trim() || saving || loading) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await createCommercePlanPractice(plan.id, { step_index: stepIndex, kind, note: note.trim() });
      setNote("");
      setMessage("已保存人工演练记录；这不是实际经营执行或效果证明。");
      void loadRecords();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存演练记录失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="commerce-practice" aria-labelledby="commerce-practice-title">
      <h4 id="commerce-practice-title">历史样本演练与离线复盘</h4>
      <p>这里记录的是对 Olist 历史样本的人工情景和反思，不能标记真实执行、效果或归因。不要填入私有商家或个人敏感数据。</p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor="commerce-practice-step">对应计划步骤</label>
        <select
          disabled={loading || saving}
          id="commerce-practice-step"
          onChange={(event) => setStepIndex(Number(event.target.value))}
          value={stepIndex}
        >
          {plan.steps.map((step, index) => (
            <option key={`${index}-${step.action}`} value={index}>步骤 {index + 1} · {step.action}</option>
          ))}
        </select>
        <label htmlFor="commerce-practice-kind">记录类型</label>
        <select
          disabled={loading || saving}
          id="commerce-practice-kind"
          onChange={(event) => setKind(event.target.value as "scenario" | "reflection")}
          value={kind}
        >
          <option value="scenario">演练情景</option>
          <option value="reflection">离线反思</option>
        </select>
        <label htmlFor="commerce-practice-note">人工记录</label>
        <textarea
          disabled={loading || saving}
          id="commerce-practice-note"
          maxLength={1000}
          onChange={(event) => setNote(event.target.value)}
          placeholder={kind === "scenario" ? "如果小规模验证，会检查什么证据与停止条件？" : "基于演练情景，哪些证据仍缺失？不能推断什么？"}
          required
          rows={3}
          value={note}
        />
        <p>同一步骤需要先保存演练情景，才能填写离线反思；记录只追加，不会改写计划或事实快照。</p>
        <button disabled={loading || saving || !note.trim()} type="submit">{saving ? "保存中..." : "保存演练记录"}</button>
      </form>
      {message ? <p role="status">{message}</p> : null}
      {error ? <p className="commerce-error" role="alert">{error}</p> : null}
      <h5>记录历史</h5>
      {loading && !records.length ? <p>正在读取演练记录...</p> : null}
      {!loading && !error && !records.length ? <p>尚无演练记录。</p> : null}
      {records.length ? (
        <ol>{records.map((record) => (
          <li key={record.id}>
            <strong>步骤 {record.step_index + 1} · {record.kind === "scenario" ? "演练情景" : "离线反思"}</strong>
            <small>{formatTimestamp(record.created_at)} · 公开样本人工演练</small>
            <p>{record.note}</p>
          </li>
        ))}</ol>
      ) : null}
      {nextOffset !== null ? (
        <button disabled={loading || saving} onClick={() => void loadMore()} type="button">
          {loading ? "读取中..." : "加载更早记录"}
        </button>
      ) : null}
    </section>
  );
}
