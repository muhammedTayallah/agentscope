import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, listProjects, setToken } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const [token, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await listProjects(token.trim()); // validates the token
      setToken(token.trim());
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "That token is not valid." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight">
          Agent<span className="text-indigo-600">Scope</span>
        </h1>
        <p className="mt-1 text-sm text-slate-500">Sign in with the server's admin token.</p>
        <label htmlFor="token" className="mt-6 block text-sm font-medium text-slate-700">
          Admin token
        </label>
        <input
          id="token"
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={(e) => setValue(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
        />
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={!token.trim() || busy}
          className="mt-4 w-full rounded-lg bg-indigo-600 py-2 font-medium text-white hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400"
        >
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
