"""Send one small nested trace. Needs AGENTSCOPE_API_KEY (and AGENTSCOPE_HOST if not local).

uv run python examples/demo.py
"""

import time

from agentscope_sdk import AgentScope

scope = AgentScope()


@scope.observe(kind="tool")
def search_docs(query: str) -> list[str]:
    time.sleep(0.05)
    return [f"Doc about {query}"]


def answer(question: str) -> str:
    with scope.trace("demo-question", input={"question": question}) as run:
        with scope.span("agent"):
            docs = search_docs(question)
            with scope.span("llm-call", kind="llm", model="gemini-3.8-flash") as llm:
                time.sleep(0.1)
                reply = f"Based on {len(docs)} doc(s): it depends."
                llm.update(output=reply, input_tokens=120, output_tokens=12)
        run.update(output=reply)
        print("trace id:", run.id)
        return reply


if __name__ == "__main__":
    print(answer("How do I reset my password?"))
    scope.flush()
