// Typed client for the AgentScope API (through the Vite /api proxy).
// The dashboard authenticates with the server's ADMIN_TOKEN, kept in localStorage.

export type Status = "ok" | "error";
export type SpanKind = "span" | "llm" | "tool";

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

interface Base {
  id: string;
  name: string;
  status: Status;
  error: string | null;
  start_time: string;
  end_time: string | null;
}

export interface TraceSummary extends Base {
  span_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Span extends Base {
  parent_id: string | null;
  kind: SpanKind;
  input: unknown;
  output: unknown;
  metadata: Record<string, unknown> | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface TraceDetail extends Base {
  input: unknown;
  output: unknown;
  metadata: Record<string, unknown> | null;
  spans: Span[];
}

export type Health = { status: "healthy" | "unhealthy"; database: "ok" | "error"; redis: "ok" | "error" };

const TOKEN_KEY = "agentscope.adminToken";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the session lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, token = getToken()): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (res.status === 401 && token && token === getToken()) {
    // Saved token no longer valid (rotated on the server): sign out.
    setToken(null);
    window.location.assign("/login");
  }
  if (!res.ok) {
    let message = `Request failed (HTTP ${res.status})`;
    try {
      const detail = (await res.json())?.detail;
      if (typeof detail === "string") message = detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  // 503 still carries a body saying which dependency is down.
  if (res.ok || res.status === 503) return (await res.json()) as Health;
  throw new Error(`Health check failed: HTTP ${res.status}`);
}

export const listProjects = (token?: string) =>
  getJson<Project[]>("/projects", token ?? getToken());

export function listTraces(
  projectId: string,
  params: { q?: string; status?: string; limit: number; offset: number },
) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  qs.set("limit", String(params.limit));
  qs.set("offset", String(params.offset));
  return getJson<{ items: TraceSummary[]; total: number }>(`/projects/${projectId}/traces?${qs}`);
}

export const getTrace = (projectId: string, traceId: string) =>
  getJson<TraceDetail>(`/projects/${projectId}/traces/${traceId}`);
