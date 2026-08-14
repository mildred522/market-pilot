import type { AnalysisFollowupResponse, AnalysisReport, DashboardOverview, IntegrationStatus, IntegrationTestResult, LocationResult, ManualLocationRequest, OperatingAnalysisMode, OperatingCostAssumptions, OperatingFileSelection, PreOpenInput, PreOpenReport, Project, RecommendationRequest, Stage, UploadedFileResult } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type AgentIntent =
  | "assess_feasibility"
  | "analyze_location"
  | "recommend_locations"
  | "diagnose_operations";

export type AgentCapability =
  | "pre_open_feasibility"
  | "location_analysis"
  | "operating_diagnosis";

export interface AgentAnalyzeRequest {
  project_id?: number;
  intent: AgentIntent;
  inputs: Record<string, unknown>;
}

export interface AgentAnalyzeResponse<T = unknown> {
  status:
    | "completed"
    | "clarification"
    | "insufficient_data"
    | "provider_failure"
    | "tool_failure";
  capability: AgentCapability;
  intent: AgentIntent;
  missing_fields: string[];
  result: T | null;
  failure: {
    category: "input" | "provider" | "tool";
    code: string;
    message: string;
    retryable: boolean;
  } | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers
      }
    });
  } catch {
    throw new Error("无法连接分析服务，请确认后端正在运行后重试。");
  }

  if (!response.ok) {
    const body = await response.text();
    let code = "";
    let providerMessage = "";
    try {
      const parsed = JSON.parse(body) as { detail?: { code?: string; message?: string } };
      code = parsed.detail?.code ?? "";
      providerMessage = parsed.detail?.message ?? "";
    } catch {
      providerMessage = body;
    }
    const friendlyMessages: Record<string, string> = {
      baidu_quota_error: "百度地图调用额度已达到限制，请稍后重试或检查 AK 配额。",
      baidu_ip_restriction_error: "当前服务器出口 IP 未通过百度地图白名单校验。",
      baidu_permission_error: "当前百度 AK 尚未开通所需的地图服务。",
      baidu_authentication_error: "百度地图 AK 鉴权失败，请检查后端配置。"
    };
    throw new Error(
      friendlyMessages[code]
      ?? providerMessage
      ?? `分析服务请求失败（HTTP ${response.status}）`
    );
  }

  return response.json() as Promise<T>;
}

export function createProject(name: string, stage: Stage): Promise<Project> {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, stage })
  });
}

export function getDashboardOverview(): Promise<DashboardOverview> {
  return request<DashboardOverview>("/dashboard/overview", { cache: "no-store" });
}

export function updateBaiduIntegration(apiKey: string): Promise<IntegrationStatus> {
  return request<IntegrationStatus>("/dashboard/integrations/baidu", {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey })
  });
}

export function updateAgentIntegration(payload: {
  apiKey: string;
  model: string;
  baseUrl: string;
  provider: string;
}): Promise<IntegrationStatus> {
  return request<IntegrationStatus>("/dashboard/integrations/agent", {
    method: "PUT",
    body: JSON.stringify({
      api_key: payload.apiKey,
      model: payload.model,
      base_url: payload.baseUrl,
      provider: payload.provider
    })
  });
}

export function clearIntegration(integration: "baidu" | "agent"): Promise<IntegrationStatus> {
  return request<IntegrationStatus>(`/dashboard/integrations/${integration}`, {
    method: "DELETE"
  });
}

export function testIntegration(integration: "baidu" | "agent"): Promise<IntegrationTestResult> {
  return request<IntegrationTestResult>(`/dashboard/integrations/${integration}/test`, {
    method: "POST"
  });
}

export function analyzePreOpen(payload: PreOpenInput): Promise<PreOpenReport> {
  return request<PreOpenReport>("/pre-open/analyze", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function analyzeWithAgent<T = unknown>(
  payload: AgentAnalyzeRequest
): Promise<AgentAnalyzeResponse<T>> {
  return request<AgentAnalyzeResponse<T>>("/agent/analyze", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getAnalysis(analysisId: number): Promise<AnalysisReport> {
  return request<AnalysisReport>(`/analysis/${analysisId}`);
}

export function askAnalysis(
  analysisId: number,
  question: string
): Promise<AnalysisFollowupResponse> {
  return request<AnalysisFollowupResponse>(`/analysis/${analysisId}/chat`, {
    method: "POST",
    body: JSON.stringify({ question })
  });
}

export function analyzeLocationManually(payload: ManualLocationRequest): Promise<LocationResult> {
  return request<LocationResult>("/pre-open/location/manual-analysis", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function recommendLocations(payload: RecommendationRequest): Promise<LocationResult> {
  return request<LocationResult>("/pre-open/location/recommendations", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getLocationSuggestions(
  kind: "city" | "district",
  query: string,
  city?: string
): Promise<string[]> {
  const params = new URLSearchParams({ kind, query });
  if (city) params.set("city", city);
  const response = await request<{ options: string[] }>(
    `/pre-open/location/suggestions?${params.toString()}`
  );
  return response.options;
}

export async function analyzeOperatingSample(
  projectId: number,
  question: string,
  analysisMode: OperatingAnalysisMode = "full"
): Promise<AnalysisReport> {
  return request<AnalysisReport>("/operating/analyze-sample", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      question,
      analysis_mode: analysisMode
    })
  });
}

export async function analyzeOperatingUploads(
  projectId: number,
  question: string,
  files: Record<"orders" | "menu_items" | "reviews", OperatingFileSelection>,
  costAssumptions: OperatingCostAssumptions,
  analysisMode: OperatingAnalysisMode = "full"
): Promise<AnalysisReport> {
  return request<AnalysisReport>("/operating/analyze", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      question,
      analysis_mode: analysisMode,
      ...files,
      cost_assumptions: costAssumptions
    })
  });
}

export async function uploadCsv(
  projectId: number,
  fileType: string,
  file: File
): Promise<UploadedFileResult> {
  const formData = new FormData();
  formData.append("project_id", String(projectId));
  formData.append("file_type", fileType);
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/files/upload`, {
    method: "POST",
    body: formData
  });

  if (!response.ok) {
    const body = await response.text();
    try {
      const parsed = JSON.parse(body) as { detail?: { message?: string } };
      throw new Error(parsed.detail?.message || `上传失败（HTTP ${response.status}）`);
    } catch (error) {
      if (error instanceof Error && error.message !== body) throw error;
      throw new Error(body || `上传失败（HTTP ${response.status}）`);
    }
  }

  return response.json() as Promise<UploadedFileResult>;
}
