"use client";

import { FormEvent, useState } from "react";
import { clearIntegration, testIntegration, updateAgentIntegration, updateBaiduIntegration } from "../lib/api";
import type { DashboardOverview, IntegrationStatus, IntegrationTestResult } from "../lib/types";

type Props = {
  integrations: DashboardOverview["integrations"];
  onChange: (name: "baidu" | "agent", status: IntegrationStatus) => void;
};

function Status({ value }: { value: IntegrationStatus }) {
  return (
    <span className={`connection-status ${value.configured ? "is-connected" : "is-idle"}`}>
      <i aria-hidden="true" />
      {value.configured ? `已连接 · ${value.source === "environment" ? "环境变量" : "本次运行"}` : "待配置"}
    </span>
  );
}

function TestResult({ value }: { value?: IntegrationTestResult }) {
  if (!value) return null;
  const detail = value.details.sample_total !== undefined
    ? `样本区域返回 ${value.details.sample_total} 个结果`
    : [value.details.provider, value.details.model].filter(Boolean).join(" · ");
  return (
    <p className={`connection-test-result ${value.ok ? "is-success" : "is-failed"}`} role="status">
      <i aria-hidden="true" />
      <span><strong>{value.ok ? "连接成功" : "连接失败"}</strong>{value.message} · {value.latency_ms} ms{detail ? ` · ${detail}` : ""}</span>
    </p>
  );
}

export default function IntegrationSettings({ integrations, onChange }: Props) {
  const [baiduKey, setBaiduKey] = useState("");
  const [agentKey, setAgentKey] = useState("");
  const [model, setModel] = useState(integrations.agent.model || "gpt-4.1-mini");
  const [baseUrl, setBaseUrl] = useState(integrations.agent.base_url || "https://api.openai.com/v1");
  const [provider, setProvider] = useState(integrations.agent.provider || "openai-compatible");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [testResults, setTestResults] = useState<Partial<Record<"baidu" | "agent", IntegrationTestResult>>>({});

  async function saveBaidu(event: FormEvent) {
    event.preventDefault();
    setBusy("baidu"); setMessage("");
    try {
      const status = await updateBaiduIntegration(baiduKey);
      onChange("baidu", status); setBaiduKey(""); setTestResults((value) => ({ ...value, baidu: undefined })); setMessage("百度地图配置已在本次后端运行中生效。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
    finally { setBusy(null); }
  }

  async function saveAgent(event: FormEvent) {
    event.preventDefault();
    setBusy("agent"); setMessage("");
    try {
      const status = await updateAgentIntegration({ apiKey: agentKey, model, baseUrl, provider });
      onChange("agent", status); setAgentKey(""); setTestResults((value) => ({ ...value, agent: undefined })); setMessage("Agent 模型配置已在本次后端运行中生效。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
    finally { setBusy(null); }
  }

  async function remove(name: "baidu" | "agent") {
    setBusy(`clear-${name}`); setMessage("");
    try {
      const status = await clearIntegration(name);
      onChange(name, status); setTestResults((value) => ({ ...value, [name]: undefined })); setMessage("运行时配置已清除；环境变量配置如存在仍会生效。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "清除失败"); }
    finally { setBusy(null); }
  }

  async function runTest(name: "baidu" | "agent") {
    setBusy(`test-${name}`); setMessage("");
    try {
      const result = await testIntegration(name);
      setTestResults((value) => ({ ...value, [name]: result }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "连接测试失败");
    } finally { setBusy(null); }
  }

  return (
    <section className="integration-panel" id="integrations" aria-labelledby="integration-title">
      <div className="dashboard-section-head">
        <div><p className="dashboard-eyebrow">Connections</p><h2 id="integration-title">数据与智能集成</h2></div>
        <p>密钥不回显、不写入浏览器存储，仅保留在当前后端进程内存。</p>
      </div>

      <div className="integration-list">
        <details className="integration-row">
          <summary>
            <span className="integration-monogram">百</span>
            <span><strong>百度地图开放平台</strong><small>城市联想、地理编码与周边 POI</small></span>
            <Status value={integrations.baidu} />
          </summary>
          <form className="integration-form" onSubmit={saveBaidu}>
            <label>服务端 AK<input type="password" autoComplete="new-password" value={baiduKey} onChange={(e) => setBaiduKey(e.target.value)} minLength={8} placeholder="输入百度地图服务端 AK" required /></label>
            <div className="integration-actions"><button disabled={busy !== null} type="submit">{busy === "baidu" ? "保存中…" : "保存并启用"}</button><button className="button-test" disabled={busy !== null || !integrations.baidu.configured} type="button" onClick={() => runTest("baidu")}>{busy === "test-baidu" ? "测试中…" : "测试连接"}</button>{integrations.baidu.source === "runtime" && <button className="button-quiet" type="button" onClick={() => remove("baidu")}>清除本次配置</button>}</div>
            <TestResult value={testResults.baidu} />
          </form>
        </details>

        <details className="integration-row">
          <summary>
            <span className="integration-monogram">AI</span>
            <span><strong>Agent 推理模型</strong><small>{integrations.agent.model || "OpenAI-compatible JSON 模型"}</small></span>
            <Status value={integrations.agent} />
          </summary>
          <form className="integration-form agent-config-grid" onSubmit={saveAgent}>
            <label>API Key<input type="password" autoComplete="new-password" value={agentKey} onChange={(e) => setAgentKey(e.target.value)} minLength={8} placeholder="输入模型服务 API Key" required /></label>
            <label>模型<input value={model} onChange={(e) => setModel(e.target.value)} required /></label>
            <label>API Base URL<input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required /></label>
            <label>Provider 标识<input value={provider} onChange={(e) => setProvider(e.target.value)} required /></label>
            <div className="integration-actions"><button disabled={busy !== null} type="submit">{busy === "agent" ? "保存中…" : "保存并启用"}</button><button className="button-test" disabled={busy !== null || !integrations.agent.configured} type="button" onClick={() => runTest("agent")}>{busy === "test-agent" ? "测试中…" : "测试连接"}</button>{integrations.agent.source === "runtime" && <button className="button-quiet" type="button" onClick={() => remove("agent")}>清除本次配置</button>}</div>
            <TestResult value={testResults.agent} />
          </form>
        </details>
      </div>
      {message && <p className="integration-message" role="status">{message}</p>}
      <p className="security-note">连接测试会发起一次最小真实请求，可能计入服务额度。后端重启后需重新输入运行时密钥；正式部署应改用密钥管理服务并增加配置权限控制。</p>
    </section>
  );
}
