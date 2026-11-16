export type Health = { status: "healthy" | "unhealthy"; database: "ok" | "error"; redis: "ok" | "error" };

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  // 503 still carries a body saying which dependency is down.
  if (res.ok || res.status === 503) return (await res.json()) as Health;
  throw new Error(`Health check failed: HTTP ${res.status}`);
}
