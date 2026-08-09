"use client";

import { useState } from "react";
import type { DashboardOverview, IntegrationStatus } from "../lib/types";
import IntegrationSettings from "./IntegrationSettings";

const stageNames = { pre_open: "开店前", operating: "经营中" };

export default function DashboardShell({ initialOverview }: { initialOverview: DashboardOverview }) {
  const [integrations, setIntegrations] = useState(initialOverview.integrations);
  const { counts, workspace, recent_analyses: recent } = initialOverview;

  function updateIntegration(name: "baidu" | "agent", status: IntegrationStatus) {
    setIntegrations((current) => ({ ...current, [name]: status }));
  }

  return (
    <main className="control-shell">
      <aside className="control-rail">
        <a className="brand-lockup" href="/"><span>MP</span><strong>Market Pilot</strong></a>
        <nav aria-label="控制台导航"><a className="is-active" href="#overview">工作台</a><a href="/pre-open#feasibility">开店前分析</a><a href="/pre-open#location">商圈与选址</a><a href="/operating#diagnosis">经营诊断</a><a href="#integrations">集成配置</a></nav>
        <div className="account-block"><span className="account-avatar">M</span><div><strong>{workspace.name}</strong><small>{workspace.role} · 单用户模式</small></div></div>
      </aside>

      <div className="control-main">
        <header className="dashboard-header" id="overview">
          <div><p className="dashboard-eyebrow">Command center / 运营中枢</p><h1>把一家店，从判断做到增长。</h1></div>
          <div className="system-state"><i /><span><strong>分析服务在线</strong><small>本地工作区 · 数据留在本机</small></span></div>
        </header>

        <section className="overview-strip" aria-label="当前数据概览">
          {[
            ["项目", counts.projects, "全部分析对象"], ["报告", counts.analyses, "已完成分析"],
            ["数据文件", counts.uploaded_files, "经营数据源"], ["选址分析", counts.location_analyses, "商圈判断"]
          ].map(([label, value, note]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}
        </section>

        <section className="flow-section" aria-labelledby="flow-title">
          <div className="dashboard-section-head"><div><p className="dashboard-eyebrow">Lifecycle</p><h2 id="flow-title">门店全周期工作流</h2></div><p>同一项目贯穿开店判断、位置筛选与经营复盘，分析结果可持续积累。</p></div>
          <div className="flow-lanes">
            <article className="flow-lane flow-lane-pre"><div className="flow-index">01</div><div className="flow-copy"><span>开店前 · {counts.pre_open_projects} 个项目</span><h3>先判断值不值得做，再决定在哪里做</h3><p>从资金结构与保本线开始，用真实周边 POI 校验竞争压力，形成开店决策依据。</p><div className="flow-steps"><a href="/pre-open#feasibility"><b>项目测算</b><small>预算、租金、回本压力</small></a><a href="/pre-open#location"><b>商圈选址</b><small>竞品、需求与候选点</small></a></div></div><a className="flow-enter" href="/pre-open#feasibility">开始评估 <span>↗</span></a></article>
            <article className="flow-lane flow-lane-operating"><div className="flow-index">02</div><div className="flow-copy"><span>开店后 · {counts.operating_projects} 个项目</span><h3>让数据说明问题，让 Agent 推进行动</h3><p>汇总订单、菜品、渠道和评论，定位利润流失环节并生成有证据的经营动作。</p><div className="flow-steps"><a href="/operating#diagnosis"><b>上传数据</b><small>订单、菜单与评价样本</small></a><a href="/operating#diagnosis"><b>Agent 诊断</b><small>归因、证据与行动清单</small></a></div></div><a className="flow-enter" href="/operating#diagnosis">进入诊断 <span>↗</span></a></article>
          </div>
        </section>

        <section className="recent-section" aria-labelledby="recent-title">
          <div className="dashboard-section-head"><div><p className="dashboard-eyebrow">Recent intelligence</p><h2 id="recent-title">最近分析</h2></div><p>{recent.length ? "回到最近一份判断，继续向 Agent 追问。" : "完成第一次分析后，报告会汇集在这里。"}</p></div>
          <div className="recent-list">
            {recent.length ? recent.map((item, index) => <a href={`/analysis/${item.id}`} key={item.id}><span className="recent-number">{String(index + 1).padStart(2, "0")}</span><span className="recent-copy"><b>{item.project_name}</b><small>{item.summary}</small></span><span className="recent-stage">{stageNames[item.stage]}</span><i>→</i></a>) : <div className="recent-empty"><strong>还没有分析报告</strong><span>可以从开店前评估或经营诊断开始。</span></div>}
          </div>
        </section>

        <IntegrationSettings integrations={integrations} onChange={updateIntegration} />
      </div>
    </main>
  );
}
