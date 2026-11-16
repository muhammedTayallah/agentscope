# agentscope-sdk

Send traces from your LLM agent to AgentScope.

```bash
uv add agentscope-sdk          # inside this repo: uv add --editable ../sdk
export AGENTSCOPE_API_KEY=ask_...            # from POST /projects
export AGENTSCOPE_HOST=http://localhost:8000 # default
```

```python
from agentscope_sdk import AgentScope

scope = AgentScope()

@scope.observe(kind="tool")          # span named after the function; captures args and result
def search(query: str) -> list[str]: ...

with scope.trace("support-run", input={"question": q}) as run:      # one agent run
    with scope.span("agent"):                                       # nested spans
        docs = search(q)
        with scope.span("llm-call", kind="llm", model="gemini-3.8-flash") as llm:
            reply = call_model(docs)
            llm.update(output=reply, input_tokens=120, output_tokens=12)
    run.update(output=reply)
```

- **Nesting** follows the call stack (`contextvars`), including across `asyncio` tasks. A new thread starts with no current trace. A `span` or `observe` call with no active trace opens one.
- **Kinds:** `span` (default), `llm` (set `model`, `input_tokens`, `output_tokens`) and `tool`.
- **Errors** raised inside a trace or span are recorded (`status: "error"`) and re-raised unchanged.
- **Never breaks your app:** events go to a bounded queue and a background thread sends them in batches. Server errors and network failures are retried up to 3 times, then dropped with a log warning. A full queue drops new events instead of blocking.
- **Exit:** queued events are flushed at exit, waiting at most 2 s. Call `scope.flush()` to wait yourself.
- **Without an API key** tracing is disabled (one warning), and your code runs as usual.

Example: `uv run python examples/demo.py`.
