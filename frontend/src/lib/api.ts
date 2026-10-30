import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type SessionCreateRequest = Schemas["SessionCreateRequest"];
export type SessionResponse = Schemas["SessionResponse"];
export type BatchUploadResponse = Schemas["BatchUploadResponse"];
export type BatchUploadItem = Schemas["BatchUploadItem"];
export type CandidateSummary = Schemas["CandidateSummary"];
export type CandidateDetailResponse = Schemas["CandidateDetailResponse"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ResumeSummary = Schemas["ResumeSummary"];
export type SelectProjectRequest = Schemas["SelectProjectRequest"];
export type RepositorySelectionResponse = Schemas["RepositorySelectionResponse"];
export type ConfirmRepositoryRequest = Schemas["ConfirmRepositoryRequest"];
export type AnalysisJobResponse = Schemas["AnalysisJobResponse"];

export interface ErrorResponse {
  code?: string;
  message?: string;
  requestId?: string;
}

export class ApiClientError extends Error {
  code: string;
  status: number;
  requestId?: string;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

type UnauthorizedHandler = () => void;
let _onUnauthorized: UnauthorizedHandler | null = null;
let _csrfToken: string | null = null;

export function setOnUnauthorized(handler: UnauthorizedHandler | null): void {
  _onUnauthorized = handler;
}

export function setCsrfToken(token: string | null): void {
  _csrfToken = token;
  if (typeof window !== "undefined") {
    if (token) {
      sessionStorage.setItem("csrf_token", token);
      try {
        localStorage.setItem("csrf_token", token);
      } catch {
        // quota or private mode
      }
    } else {
      sessionStorage.removeItem("csrf_token");
      try {
        localStorage.removeItem("csrf_token");
      } catch {
        // ignore
      }
    }
  }
}

export function getCsrfToken(): string | null {
  if (!_csrfToken && typeof window !== "undefined") {
    _csrfToken = sessionStorage.getItem("csrf_token");
    if (!_csrfToken) {
      try {
        _csrfToken = localStorage.getItem("csrf_token");
      } catch {
        // ignore
      }
    }
    if (!_csrfToken) {
      const csrfCookie = document.cookie
        .split("; ")
        .find((cookie) => cookie.startsWith("csrf_token="));
      _csrfToken = csrfCookie ? decodeURIComponent(csrfCookie.slice("csrf_token=".length)) : null;
    }
  }
  return _csrfToken;
}

let _fetchingCsrf: Promise<string | null> | null = null;

async function refreshCsrf(): Promise<string | null> {
  if (_fetchingCsrf) return _fetchingCsrf;
  _fetchingCsrf = (async () => {
    try {
      const res = await fetch("/api/v1/session", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        if (data.csrfToken) {
          setCsrfToken(data.csrfToken);
          return data.csrfToken;
        }
      }
    } catch {
      // offline or unauth
    } finally {
      _fetchingCsrf = null;
    }
    return null;
  })();
  return _fetchingCsrf;
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});

  // For state-changing operations, automatically supply CSRF token
  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    let csrf = getCsrfToken();
    if (!csrf && endpoint !== "/api/v1/session") {
      csrf = await refreshCsrf();
    }
    if (csrf && !headers.has("x-csrf-token")) {
      headers.set("x-csrf-token", csrf);
    }
  }

  // Ensure same-origin credentials (HttpOnly cookie) and disable cache
  const config: RequestInit = {
    ...options,
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  };

  const response = await fetch(endpoint, config);

  if (response.status === 401) {
    if (_onUnauthorized) {
      _onUnauthorized();
    }
  }

  if (!response.ok) {
    let errorCode = "API_ERROR";
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;
    let requestId: string | undefined =
      response.headers.get("x-request-id") || undefined;

    try {
      const errJson = (await response.json()) as ErrorResponse;
      if (errJson.code) errorCode = errJson.code;
      if (errJson.message) errorMessage = errJson.message;
      if (errJson.requestId) requestId = errJson.requestId;
    } catch {
      // Non-JSON error payload
    }

    throw new ApiClientError(response.status, errorCode, errorMessage, requestId);
  }

  // 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Authentication & Session
// ---------------------------------------------------------------------------

export async function getSession(): Promise<SessionResponse> {
  const data = await request<SessionResponse>("/api/v1/session", {
    method: "GET",
  });
  if (data.csrfToken) {
    setCsrfToken(data.csrfToken);
  }
  return data;
}

export async function login(password: string): Promise<SessionResponse> {
  const data = await request<SessionResponse>("/api/v1/session", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password }),
  });
  if (data.csrfToken) {
    setCsrfToken(data.csrfToken);
  }
  return data;
}

export async function logout(): Promise<{ status: string }> {
  try {
    return await request<{ status: string }>("/api/v1/session", {
      method: "DELETE",
    });
  } finally {
    setCsrfToken(null);
  }
}

// ---------------------------------------------------------------------------
// Resumes & Multi-File Batch Intake
// ---------------------------------------------------------------------------

export async function uploadResumeBatches(files: File[]): Promise<BatchUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  return request<BatchUploadResponse>("/api/v1/resume-batches", {
    method: "POST",
    body: formData,
  });
}

// ---------------------------------------------------------------------------
// Candidates & Projects
// ---------------------------------------------------------------------------

export async function listCandidates(): Promise<CandidateSummary[]> {
  return request<CandidateSummary[]>("/api/v1/candidates");
}

export async function getCandidate(candidateId: string): Promise<CandidateDetailResponse> {
  return request<CandidateDetailResponse>(`/api/v1/candidates/${candidateId}`);
}

export async function selectCandidateProject(
  candidateId: string,
  projectId: string
): Promise<CandidateDetailResponse> {
  return request<CandidateDetailResponse>(
    `/api/v1/candidates/${candidateId}/selected-project`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ projectId }),
    }
  );
}

export async function deleteCandidate(
  candidateId: string
): Promise<{ status: string; candidateId: string }> {
  return request<{ status: string; candidateId: string }>(
    `/api/v1/candidates/${candidateId}`,
    {
      method: "DELETE",
    }
  );
}

// ---------------------------------------------------------------------------
// Repositories & Analysis
// ---------------------------------------------------------------------------

export async function listProjectRepositories(
  projectId: string,
  limit?: number
): Promise<RepositorySelectionResponse[]> {
  const query = limit ? `?limit=${limit}` : "";
  return request<RepositorySelectionResponse[]>(
    `/api/v1/projects/${projectId}/repositories${query}`
  );
}

export async function discoverProjectRepositories(
  projectId: string,
  limit: number = 10
): Promise<RepositorySelectionResponse[]> {
  return request<RepositorySelectionResponse[]>(
    `/api/v1/projects/${projectId}/discover-repositories?limit=${limit}`,
    {
      method: "POST",
    }
  );
}

export async function confirmRepositorySelection(
  projectId: string,
  data: ConfirmRepositoryRequest
): Promise<RepositorySelectionResponse> {
  return request<RepositorySelectionResponse>(
    `/api/v1/projects/${projectId}/repository-selection`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );
}

export async function triggerProjectAnalysis(
  projectId: string
): Promise<AnalysisJobResponse> {
  return request<AnalysisJobResponse>(
    `/api/v1/projects/${projectId}/analyses`,
    {
      method: "POST",
    }
  );
}

export async function getJobStatus(jobId: string): Promise<AnalysisJobResponse> {
  return request<AnalysisJobResponse>(`/api/v1/jobs/${jobId}`);
}

export async function cancelJob(jobId: string): Promise<AnalysisJobResponse> {
  return request<AnalysisJobResponse>(`/api/v1/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function getAnalysisReport(jobId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/v1/analyses/${jobId}`);
}
