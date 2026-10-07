"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { CommercePlanPractice } from "@/components/CommercePlanPractice";
import { approveCommercePlan, askCommerceTalk, createCommercePlan, createProject, getCommercePlan, getCommercePlans, getCurrentUser, getProjectHistory } from "@/lib/api";
import type { AuthenticatedUser, CommerceComparisonWindows, CommerceInteractionRequest, CommercePlanResponse, CommercePlanSummary, CommerceTalkResponse, Project } from "@/lib/types";

type AgentMode = "talk" | "plan";
type TalkExecution = CommerceTalkResponse["executions"][number];

const toolNames: Record<string, string> = {
  commerce_analyze_product_sales: "商品销售事实",
  commerce_analyze_category_sales: "品类销售事实",
  commerce_compare_category_trends: "品类趋势对比",
  commerce_compare_product_trends: "商品趋势对比",
  commerce_discover_hot_products: "热点商品候选"
};

function formatAmount(value: number | string | null | undefined): string {
  if (value == null) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatTimestamp(value: string): string {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Date(normalized).toLocaleString("zh-CN");
}

function productLabel(category: string | null, productId: string): string {
  const shortId = productId.length > 12 ? `${productId.slice(0, 8)}…${productId.slice(-4)}` : productId;
  return `${category ?? "未分类"} · ${shortId}`;
}

function TalkExecutionCard({ execution }: { execution: TalkExecution }) {
  const data = execution.data;
  return (
    <article className="commerce-agent-card">
      <h4>{toolNames[execution.tool_name] ?? execution.tool_name} · {execution.status === "completed" ? "已计算" : "未完成"}</h4>
      {data?.metrics ? (
        <>
          <p>当前窗口 {data.included_order_count ?? 0} 笔有效订单；以下展示销售额前 5 个商品。</p>
          <ol>{data.metrics.slice(0, 5).map((metric) => (
            <li key={metric.item_id} title={metric.product_id}>
              {productLabel(metric.category_name, metric.product_id)}：销售额 {formatAmount(metric.gross_amount)} {metric.currency ?? ""}，销量 {formatAmount(metric.units_sold)}
            </li>
          ))}</ol>
        </>
      ) : null}
      {data?.categories ? (
        <>
          <p>当前窗口包含 {data.categories.length} 个品类；以下展示销售额前 5 个品类。</p>
          <ol>{data.categories.slice(0, 5).map((category) => (
            <li key={category.category_name ?? "uncategorized"}>
              {category.category_name ?? "未分类"}：销售额 {formatAmount(category.gross_amount)} {category.currency ?? ""}，销量 {formatAmount(category.units_sold)}，商品数 {category.product_count}
            </li>
          ))}</ol>
        </>
      ) : null}
      {data?.category_trends ? (
        <>
          <p>两窗共有 {data.category_trends.length} 个品类；以下按当前窗口销售额展示前 5 个。</p>
          <ol>{[...data.category_trends].sort((left, right) =>
            Number(right.current?.gross_amount ?? 0) - Number(left.current?.gross_amount ?? 0)
          ).slice(0, 5).map((category) => (
            <li key={category.category_name ?? "uncategorized"}>
              {category.category_name ?? "未分类"}：当前 {formatAmount(category.current?.gross_amount)}，基线 {formatAmount(category.previous?.gross_amount)}，销售额变化 {category.gross_amount_growth_rate == null ? "基线不足" : `${formatAmount(Number(category.gross_amount_growth_rate) * 100)}%`}
            </li>
          ))}</ol>
        </>
      ) : null}
      {data?.items ? (
        <>
          <p>两窗共有 {data.items.length} 个商品；以下按当前窗口销售额展示前 5 个。</p>
          <ol>{[...data.items].sort((left, right) =>
            Number(right.current?.gross_amount ?? 0) - Number(left.current?.gross_amount ?? 0)
          ).slice(0, 5).map((item) => (
            <li key={item.item_id} title={item.product_id}>
              {productLabel(item.category_name, item.product_id)}：当前 {formatAmount(item.current?.gross_amount)}，基线 {formatAmount(item.previous?.gross_amount)}
            </li>
          ))}</ol>
        </>
      ) : null}
      {data?.candidates ? (
        <>
          <p>识别 {data.candidates.length} 个热点候选；以下展示前 5 个，不代表未来需求。</p>
          <ol>{data.candidates.slice(0, 5).map((candidate) => (
            <li key={candidate.item_id} title={candidate.product_id}>
              {productLabel(candidate.category_name, candidate.product_id)}：{candidate.evidence.join("；")}
            </li>
          ))}</ol>
        </>
      ) : null}
      {execution.evidence.length ? <p>来源：{execution.evidence.join(" · ")}</p> : null}
      {execution.warnings.map((warning) => <p key={warning} className="commerce-agent-warning">{warning}</p>)}
      {execution.error_code ? <p className="commerce-agent-warning">错误代号：{execution.error_code}</p> : null}
    </article>
  );
}

export function CommerceAgentWorkspace({ snapshotId, comparison }: { snapshotId: string; comparison: CommerceComparisonWindows }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [loadingWorkspace, setLoadingWorkspace] = useState(true);
  const [mode, setMode] = useState<AgentMode>("talk");
  const [question, setQuestion] = useState("哪些商品销售额领先？");
  const [pending, setPending] = useState<"talk" | "plan" | "approval" | "project" | "plan-read" | null>(null);
  const [error, setError] = useState("");
  const [talk, setTalk] = useState<CommerceTalkResponse | null>(null);
  const [plan, setPlan] = useState<CommercePlanResponse | null>(null);
  const [plans, setPlans] = useState<CommercePlanSummary[]>([]);
  const [nextPlanOffset, setNextPlanOffset] = useState<number | null>(null);
  const [loadingPlans, setLoadingPlans] = useState(false);
  const [plansError, setPlansError] = useState("");
  const planListRequestId = useRef(0);

  useEffect(() => {
    let active = true;
    void Promise.all([getCurrentUser(), getProjectHistory()])
      .then(([account, history]) => {
        if (!active) return;
        setUser(account);
        setProjects(history.items);
        setProjectId(history.items[0]?.id ?? null);
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "工作区加载失败");
      })
      .finally(() => {
        if (active) setLoadingWorkspace(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setPlans([]);
    setNextPlanOffset(null);
    setPlansError("");
    if (user?.is_admin && projectId) void refreshPlans(projectId);
    return () => {
      planListRequestId.current += 1;
    };
  }, [user?.is_admin, projectId, snapshotId]);

  async function refreshPlans(currentProjectId: number) {
    const requestId = ++planListRequestId.current;
    setLoadingPlans(true);
    setPlansError("");
    try {
      const page = await getCommercePlans(currentProjectId, snapshotId);
      if (requestId !== planListRequestId.current) return;
      setPlans(page.items);
      setNextPlanOffset(page.next_offset);
    } catch (caught) {
      if (requestId === planListRequestId.current) setPlansError(caught instanceof Error ? caught.message : "计划列表加载失败");
    } finally {
      if (requestId === planListRequestId.current) setLoadingPlans(false);
    }
  }

  async function loadMorePlans() {
    if (!projectId || nextPlanOffset === null || loadingPlans || pending) return;
    const requestId = ++planListRequestId.current;
    setLoadingPlans(true);
    setPlansError("");
    try {
      const page = await getCommercePlans(projectId, snapshotId, nextPlanOffset);
      if (requestId !== planListRequestId.current) return;
      setPlans((items) => [...items, ...page.items.filter((item) => !items.some((current) => current.id === item.id))]);
      setNextPlanOffset(page.next_offset);
    } catch (caught) {
      if (requestId === planListRequestId.current) setPlansError(caught instanceof Error ? caught.message : "更多计划加载失败");
    } finally {
      if (requestId === planListRequestId.current) setLoadingPlans(false);
    }
  }

  async function openPlan(planId: number) {
    if (!projectId || pending) return;
    setPending("plan-read");
    setError("");
    try {
      const saved = await getCommercePlan(planId);
      if (saved.project_id !== projectId || saved.snapshot_id !== snapshotId) {
        throw new Error("该计划不属于当前项目与快照");
      }
      setPlan(saved);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取计划失败");
    } finally {
      setPending(null);
    }
  }

  async function addProject() {
    setPending("project");
    setError("");
    try {
      const created = await createProject("电商 Benchmark 演示", "operating");
      setProjects((items) => [created, ...items].slice(0, 50));
      setProjectId(created.id);
      setTalk(null);
      setPlan(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建项目失败");
    } finally {
      setPending(null);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !question.trim() || pending || (mode === "plan" && (!user?.is_admin || loadingPlans))) return;
    const request: CommerceInteractionRequest = {
      question: question.trim(),
      interaction: { mode, scope: { mode: "benchmark", project_id: projectId, snapshot_id: snapshotId } },
      previous_window: comparison.baseline_window,
      current_window: comparison.current_window,
      item_level: "product"
    };
    setPending(mode);
    setError("");
    try {
      if (mode === "talk") setTalk(await askCommerceTalk(request));
      else {
        setPlan(await createCommercePlan(request));
        void refreshPlans(projectId);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败");
    } finally {
      setPending(null);
    }
  }

  async function approve() {
    if (!plan || plan.status !== "draft" || !user?.is_admin || pending) return;
    setPending("approval");
    setError("");
    try {
      setPlan(await approveCommercePlan(plan.id));
      if (projectId) void refreshPlans(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "审批失败");
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="commerce-agent-panel" aria-labelledby="commerce-agent-title">
      <div className="section-heading">
        <div><p className="kicker">Evidence workspace</p><h2 id="commerce-agent-title">基于快照提问</h2></div>
        <p>Talk 是关键词路由的只读事实查询，Plan 是需管理员审批的草案；当前不接实时商家数据，也不执行操作。</p>
      </div>
      {loadingWorkspace ? <p className="commerce-empty">正在读取账户和项目...</p> : null}
      {!loadingWorkspace ? (
        <>
          <div className="commerce-agent-project">
            <label htmlFor="commerce-agent-project">授权项目</label>
            <select
              id="commerce-agent-project"
              disabled={pending !== null || loadingPlans || !projects.length}
              onChange={(event) => {
                setProjectId(Number(event.target.value));
                setTalk(null);
                setPlan(null);
                setError("");
              }}
              value={projectId ?? ""}
            >
              {!projects.length ? <option value="">尚无项目</option> : null}
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name} · #{project.id}</option>)}
            </select>
            <button disabled={pending !== null} onClick={() => void addProject()} type="button">
              {pending === "project" ? "创建中..." : "创建演示项目"}
            </button>
          </div>
          <p className="commerce-agent-hint">列出最近 50 个项目，仅用于当前账号的访问控制；不把餐饮项目数据当作电商事实。快照和比较窗口固定引用上方选择。</p>
          <div className="commerce-agent-modes" role="group" aria-label="分析模式">
            <button aria-pressed={mode === "talk"} className={mode === "talk" ? "active" : ""} onClick={() => { setMode("talk"); setError(""); }} type="button">Talk · 事实查询</button>
            <button aria-pressed={mode === "plan"} className={mode === "plan" ? "active" : ""} disabled={!user?.is_admin} onClick={() => { setMode("plan"); setError(""); }} type="button">Plan · 计划草案</button>
          </div>
          {!user?.is_admin ? <p className="commerce-agent-hint">当前账号仅可使用 Talk；Plan 由服务端限制为管理员。</p> : null}
          {mode === "plan" && user?.is_admin && projectId ? (
            <div className="commerce-agent-history">
              <h3>此项目和快照的历史计划</h3>
              {loadingPlans && !plans.length ? <p>正在读取计划...</p> : null}
              {plansError ? <p className="commerce-error" role="alert">{plansError}</p> : null}
              {!loadingPlans && !plansError && !plans.length ? <p>尚无已保存的计划草案。</p> : null}
              {plans.length ? (
                <ul>{plans.map((item) => (
                  <li key={item.id}>
                    <button disabled={pending !== null || loadingPlans} onClick={() => void openPlan(item.id)} type="button">
                      #{item.id} · {item.title} · {item.status === "approved" ? "已审批" : "待审批"}
                    </button>
                    <small>{formatTimestamp(item.created_at)} · {item.question}</small>
                  </li>
                ))}</ul>
              ) : null}
              {nextPlanOffset !== null ? (
                <button disabled={loadingPlans || pending !== null} onClick={() => void loadMorePlans()} type="button">
                  {loadingPlans ? "读取中..." : "加载更早计划"}
                </button>
              ) : null}
            </div>
          ) : null}
          <form className="commerce-agent-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="commerce-agent-question">{mode === "talk" ? "关于商品、品类销售、趋势或热点提问" : "计划目标"}</label>
            <textarea id="commerce-agent-question" maxLength={2000} onChange={(event) => setQuestion(event.target.value)} required rows={3} value={question} />
            <div className="commerce-agent-prompts">
              {(["哪些商品销售额领先？", "哪些品类销售额增长了？", "最近哪些商品增长较快？", "有哪些热点商品候选？"] as const).map((prompt) => (
                <button key={prompt} onClick={() => setQuestion(prompt)} type="button">{prompt}</button>
              ))}
            </div>
            <button className="commerce-agent-submit" disabled={!projectId || pending !== null || !question.trim() || (mode === "plan" && loadingPlans)} type="submit">
              {pending === mode ? "分析中..." : mode === "talk" ? "查询历史事实" : "生成待审批计划"}
            </button>
          </form>
          {error ? <p className="commerce-error" role="alert">{error}</p> : null}
          {mode === "talk" && talk ? (
            <div className="commerce-agent-result" aria-live="polite">
              <h3>{talk.status === "completed" ? "查询结果" : "需要收窄问题或补充数据"}</h3>
              <p>快照 {snapshotId} · 当前 {comparison.current_window.start.slice(0, 10)} 至 {comparison.current_window.end.slice(0, 10)}（结束时间不含）</p>
              {talk.query_spec ? (
                <details className="commerce-query-spec">
                  <summary>查看本次查询口径</summary>
                  <p>指标代号：{talk.query_spec.metric_codes.join(" · ")} · 粒度：{talk.query_spec.result_grain}</p>
                  <p>{talk.query_spec.definitions.join("；")}</p>
                  <small>来源：{talk.query_spec.source_type ?? "未绑定"} · 时间字段：{talk.query_spec.time_basis ?? "未绑定"} · 状态：{talk.query_spec.order_statuses.join("、") || "未声明"}</small>
                  <small>证据字段：{talk.query_spec.evidence_fields.join("、") || "未声明"}</small>
                  <small>不包含：{talk.query_spec.excludes.join("、") || "无"}</small>
                </details>
              ) : null}
              {talk.executions.map((execution) => <TalkExecutionCard execution={execution} key={execution.tool_name} />)}
              {talk.suggestions.map((suggestion) => <p key={suggestion}>{suggestion}</p>)}
              {talk.limitations.map((limitation) => <p className="commerce-agent-warning" key={limitation}>{limitation}</p>)}
            </div>
          ) : null}
          {mode === "plan" && plan ? (
            <div className="commerce-agent-result" aria-live="polite">
              <h3>{plan.title} · #{plan.id}</h3>
              <p>状态：{plan.status === "approved" ? "已审批" : "待审批"} · {plan.objective}</p>
              <p>绑定快照 {plan.snapshot_id}；审批不代表计划已执行，也不证明建议有效。</p>
              <ol>{plan.steps.map((step, index) => (
                <li className="commerce-agent-card" key={`${index}-${step.action}`}>
                  <strong>{step.action}</strong>
                  <p>{step.rationale}</p>
                  <p>验证信号：{step.success_signal}</p>
                  <small>证据：{step.evidence.join(" · ")}</small>
                </li>
              ))}</ol>
              {plan.limitations.map((limitation) => <p className="commerce-agent-warning" key={limitation}>{limitation}</p>)}
              {plan.status === "draft" && user?.is_admin ? (
                <button className="commerce-agent-submit" disabled={pending !== null} onClick={() => void approve()} type="button">
                  {pending === "approval" ? "审批中..." : "确认审批此计划"}
                </button>
              ) : null}
              {plan.status === "approved" ? <CommercePlanPractice key={plan.id} plan={plan} /> : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
