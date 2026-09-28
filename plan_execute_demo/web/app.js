const state = { ordersCsv: "", menuCsv: "", ordersMapping: null, menuMapping: null };
const $ = (id) => document.getElementById(id);

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败");
  return body;
}

async function getJson(path) {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败");
  return body;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function renderMappings() {
  const items = [
    state.ordersMapping && { name: "订单", data: state.ordersMapping },
    state.menuMapping && { name: "菜品成本", data: state.menuMapping }
  ].filter(Boolean);
  $("mapping").textContent = items.length
    ? JSON.stringify(items, null, 2)
    : "未上传文件，当前使用内置样例。";
}

async function inspectFile(file, kind) {
  if (!file) return;
  const csv = await file.text();
  const inspection = await api("/api/inspect", { csv, kind });
  if (kind === "orders") {
    state.ordersCsv = csv;
    state.ordersMapping = inspection.suggested_mapping;
  } else {
    state.menuCsv = csv;
    state.menuMapping = inspection.suggested_mapping;
  }
  renderMappings();
}

function renderPlan(report) {
  const executions = new Map(report.trace.tool_executions.map((item) => [item.tool, item]));
  $("plan-list").replaceChildren(...report.plan.tools.map((item) => {
    const row = document.createElement("li");
    const outcome = executions.get(item.tool);
    row.className = outcome?.status === "completed" ? "done" : "";
    row.innerHTML = `<code>${item.tool}</code><br>${item.reason}`;
    return row;
  }));
  const replan = report.trace.replan;
  $("replan").textContent = replan.attempted
    ? `已重规划：${replan.failed_tool} → ${replan.replacement_tools.join(", ")}`
    : "没有发生重规划";
}

function renderReport(report) {
  const findings = $("findings");
  findings.className = "findings";
  findings.replaceChildren(...report.findings.map((finding) => {
    const article = $("finding-template").content.firstElementChild.cloneNode(true);
    article.querySelector("p").textContent = finding.text;
    article.querySelector("code").textContent = finding.evidence_ids.join(" · ");
    return article;
  }));
  const facts = $("evidence");
  facts.replaceChildren(...report.evidence.map((fact) => {
    const row = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = `${fact.id} · ${fact.path}`;
    row.append(title, document.createTextNode(`${fact.label}: ${fact.value}`));
    return row;
  }));
  $("composition").textContent = report.trace.composition;
}

async function analyze() {
  const button = $("analyze");
  button.disabled = true;
  $("run-status").textContent = "正在规划与执行…";
  try {
    const payload = {
      question: $("question").value.trim(), mode: selectedMode(),
      orders_csv: state.ordersCsv, menu_csv: state.menuCsv,
      orders_mapping: state.ordersMapping, menu_mapping: state.menuMapping
    };
    const report = await api("/api/analyze", payload);
    renderPlan(report);
    renderReport(report);
    $("run-status").textContent = `已完成 · ${report.trace.validation}`;
  } catch (error) {
    $("run-status").textContent = `无法运行：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function renderLlmStatus(config) {
  $("llm-status").textContent = config.configured
    ? `已配置：${config.model}。密钥仅保留在当前服务进程。`
    : "未配置，当前使用确定性报告。";
}

async function saveLlmConfig() {
  const button = $("save-llm");
  button.disabled = true;
  $("llm-status").textContent = "正在保存本地服务配置…";
  try {
    const config = await api("/api/llm-config", {
      endpoint: $("llm-endpoint").value.trim(),
      model: $("llm-model").value.trim(),
      api_key: $("llm-key").value.trim()
    });
    $("llm-key").value = "";
    renderLlmStatus(config);
  } catch (error) {
    $("llm-status").textContent = `无法保存：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function loadLlmStatus() {
  try {
    const config = await getJson("/api/llm-config");
    if (config.endpoint) $("llm-endpoint").value = config.endpoint;
    if (config.model) $("llm-model").value = config.model;
    renderLlmStatus(config);
  } catch {
    $("llm-status").textContent = "无法读取模型配置。";
  }
}

$("orders-file").addEventListener("change", (event) => inspectFile(event.target.files[0], "orders"));
$("menu-file").addEventListener("change", (event) => inspectFile(event.target.files[0], "menu"));
$("analyze").addEventListener("click", analyze);
$("save-llm").addEventListener("click", saveLlmConfig);
loadLlmStatus();
