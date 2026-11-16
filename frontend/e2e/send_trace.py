"""Send the trace that e2e/flow.mjs checks. Run from sdk/:

    AGENTSCOPE_API_KEY=ask_... uv run python ../frontend/e2e/send_trace.py "<run name>"
"""

import sys
import time

from agentscope_sdk import AgentScope

scope = AgentScope()
run_name = sys.argv[1] if len(sys.argv) > 1 else "support-question"


@scope.observe(kind="tool")
def search_docs(query: str) -> list[str]:
    time.sleep(0.03)
    return ["Passwords can be reset from Settings > Security."]


with scope.trace(run_name, input={"question": "How do I reset my password?"}) as run:
    with scope.span("agent"):
        with scope.span("plan"):
            time.sleep(0.01)
        docs = search_docs("reset password")
        with scope.span("answer"):
            with scope.span("llm-call", kind="llm", model="gemini-3.8-flash") as llm:
                llm.update(
                    input={"prompt": "Answer using: " + docs[0]},
                    output="Reset it from Settings > Security.",
                    input_tokens=120,
                    output_tokens=12,
                )
                time.sleep(0.05)
            try:
                with scope.span("format"):
                    raise ValueError("bad markdown")
            except ValueError:
                pass  # the agent recovers; the span keeps the error
    run.update(output="Reset it from Settings > Security.")

print("sent", run.id, "delivered:", scope.flush())
