import { Link, Navigate, Outlet, useNavigate, useParams } from "react-router-dom";

import { fetchHealth, getToken, listProjects, setToken } from "../lib/api";
import { useFetch } from "../lib/useFetch";

/** Header with project switcher and health; requires a saved admin token. */
export function Layout() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const projects = useFetch(() => listProjects(), []);
  const health = useFetch(fetchHealth, []);

  if (!getToken()) return <Navigate to="/login" replace />;

  const healthy = health.data?.status === "healthy";
  return (
    <div className="min-h-dvh bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            Agent<span className="text-indigo-600">Scope</span>
          </Link>
          {projects.data && projects.data.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-slate-500">
              Project
              <select
                aria-label="Project"
                value={projectId ?? ""}
                onChange={(e) => navigate(`/p/${e.target.value}/runs`)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-slate-900"
              >
                {projects.data.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="ml-auto flex items-center gap-4 text-sm">
            <span className="flex items-center gap-1.5 text-slate-500" title="Backend health">
              <span
                className={`size-2 rounded-full ${health.loading ? "bg-slate-300" : healthy ? "bg-emerald-500" : "bg-red-500"}`}
                aria-hidden
              />
              {health.loading ? "checking…" : healthy ? "healthy" : "backend unavailable"}
            </span>
            <button
              type="button"
              onClick={() => {
                setToken(null);
                navigate("/login");
              }}
              className="text-slate-500 hover:text-slate-900"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

/** "/" -> the first project's runs. */
export function ProjectsHome() {
  const projects = useFetch(() => listProjects(), []);
  if (projects.loading) return <p className="text-sm text-slate-400">Loading projects…</p>;
  if (projects.error) return <p className="text-sm text-red-600">{projects.error.message}</p>;
  const first = projects.data?.[0];
  if (first) return <Navigate to={`/p/${first.id}/runs`} replace />;
  return (
    <div className="mx-auto max-w-xl rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <h1 className="text-lg font-semibold">No projects yet</h1>
      <p className="mt-2 text-sm text-slate-500">Create one with the API, then send traces with the SDK:</p>
      <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-900 p-3 text-left text-xs text-slate-100">
        {`curl -X POST localhost:8000/projects \\
  -H "Authorization: Bearer $ADMIN_TOKEN" \\
  -H "Content-Type: application/json" -d '{"name": "My agent"}'`}
      </pre>
    </div>
  );
}
