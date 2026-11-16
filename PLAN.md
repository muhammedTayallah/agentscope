# AgentScope Plan

Work one phase at a time. Stop when the phase's **Done when** is met.

1. **Scaffold + projects/API keys:** Docker Compose (Postgres, Redis, backend, ARQ worker, frontend), a health endpoint, and projects whose API keys are generated once and stored hashed.
   **Done when:** `docker compose up` starts everything, a project and API key can be created, and a request with a bad key gets 401.

2. **Ingestion API + SDK:** a batch ingestion endpoint for traces and spans, plus `agentscope-sdk` with a decorator and context manager that nest spans and send them in the background.
   **Done when:** a script using the SDK produces a correctly nested trace in the database, and an unreachable server never crashes the instrumented app.

3. **Runs list + span tree UI:** a filterable runs list and a run detail page with a collapsible span tree showing inputs, outputs, timings and errors.
   **Done when:** a trace sent by the SDK appears in the UI with the right nesting, and clicking a span shows its details.

4. **Metrics + charts:** token cost per model, latency percentiles, error rate and volume over time, as Recharts dashboards.
   **Done when:** the charts match totals computed by hand for a seeded dataset.

5. **Instrument a real agent:** a real tool-using LLM agent in `evals/` traced end to end through the SDK.
   **Done when:** a real agent run shows its LLM calls, tool calls, cost and latency in the dashboard.

6. **Eval system:** datasets, eval runs executed by ARQ workers, deterministic scorers plus an LLM-as-judge, and side-by-side comparison of agent versions.
   **Done when:** running one dataset against two agent versions shows per-item scores and a comparison view.

7. **Load test:** load-test ingestion and fix the bottlenecks found.
   **Done when:** a recorded load test meets a target ingest rate and p95 latency agreed at the start of the phase, with results in `docs/`.

8. **Deploy:** production images, CI, and a public demo.
   **Done when:** CI is green and the app is reachable at a public URL.
