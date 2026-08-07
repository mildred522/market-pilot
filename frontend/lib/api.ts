import type { AnalysisReport, LocationResult, ManualLocationRequest, PreOpenInput, PreOpenReport, Project, RecommendationRequest, Stage, UploadedFileResult } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    }
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function createProject(name: string, stage: Stage): Promise<Project> {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, stage })
  });
}

export function analyzePreOpen(payload: PreOpenInput): Promise<PreOpenReport> {
  return request<PreOpenReport>("/pre-open/analyze", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getAnalysis(analysisId: number): Promise<AnalysisReport> {
  return request<AnalysisReport>(`/analysis/${analysisId}`);
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

export async function analyzeOperatingSample(projectId: number): Promise<AnalysisReport> {
  return request<AnalysisReport>("/operating/analyze-sample", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      question: "最近营业额下降，问题出在哪里？"
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
    const message = await response.text();
    throw new Error(message || `Upload failed with ${response.status}`);
  }

  return response.json() as Promise<UploadedFileResult>;
}
