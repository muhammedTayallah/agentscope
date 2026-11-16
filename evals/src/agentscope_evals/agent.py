"""A small tool-using support agent on Gemini, traced end to end with agentscope-sdk.

Trace layout for one question:
    support-agent (trace; metadata: agent_version, model)
      gemini (llm)            model, input/output tokens, the model's reply
      get_order (tool)        arguments -> result (or error)
      gemini (llm)
      ...
"""

from dataclasses import dataclass
from typing import Any

from agentscope_sdk import AgentScope
from google.genai import types

from agentscope_evals.tools import DECLARATIONS, TOOLS, ToolError

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # fastest and cheapest in the Phase 5 comparison

SYSTEM_PROMPT = """You are the customer-support assistant for Northwind Gadgets, an online shop.

Use the tools instead of guessing: search_kb for any policy (returns, shipping, warranty, \
payment), get_order for anything about a specific order, and calculate for any arithmetic. \
If a tool says an order doesn't exist, tell the customer and ask them to check the id. \
Answer in two or three short sentences, with the concrete numbers and dates from the tools."""


class StepLimitExceeded(RuntimeError):
    pass


@dataclass
class AgentResult:
    answer: str
    trace_id: str
    steps: int
    tool_calls: list[str]


class SupportAgent:
    def __init__(
        self,
        client: Any,
        scope: AgentScope,
        *,
        model: str = DEFAULT_MODEL,
        version: str = "v1",
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 6,
    ):
        self.client = client
        self.scope = scope
        self.model = model
        self.version = version
        self.max_steps = max_steps
        self.config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[
                types.Tool(
                    function_declarations=[types.FunctionDeclaration(**d) for d in DECLARATIONS]
                )
            ],
            # We run the tool loop ourselves so each call becomes its own span.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def run(self, question: str) -> AgentResult:
        meta = {"agent_version": self.version, "model": self.model}
        with self.scope.trace(
            "support-agent", input={"question": question}, metadata=meta
        ) as trace:
            contents = [types.Content(role="user", parts=[types.Part(text=question)])]
            tool_calls: list[str] = []
            for step in range(1, self.max_steps + 1):
                response = self._call_model(contents)
                # Keep the model's turn unchanged: Gemini 3 needs its thought signatures back.
                contents.append(response.candidates[0].content)
                calls = response.function_calls or []
                if not calls:
                    answer = (response.text or "").strip()
                    trace.update(output=answer)
                    return AgentResult(answer, trace.id, step, tool_calls)
                contents.append(
                    types.Content(role="user", parts=[self._run_tool(c, tool_calls) for c in calls])
                )
            raise StepLimitExceeded(f"No answer after {self.max_steps} model calls.")

    def _call_model(self, contents: list[types.Content]) -> types.GenerateContentResponse:
        with self.scope.span("gemini", kind="llm", model=self.model) as span:
            span.update(input={"messages": len(contents), "last": _part_summary(contents[-1])})
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=self.config
            )
            usage = response.usage_metadata
            if usage is not None:
                span.update(
                    input_tokens=usage.prompt_token_count or 0,
                    # Thinking tokens are billed as output.
                    output_tokens=(usage.candidates_token_count or 0)
                    + (usage.thoughts_token_count or 0),
                )
            calls = response.function_calls or []
            span.update(
                output={"tool_calls": [{"name": c.name, "args": c.args} for c in calls]}
                if calls
                else response.text
            )
            return response

    def _run_tool(self, call: types.FunctionCall, log: list[str]) -> types.Part:
        log.append(call.name)
        args = dict(call.args or {})
        try:
            with self.scope.span(call.name, kind="tool", input=args) as span:
                fn = TOOLS.get(call.name)
                if fn is None:
                    raise ToolError(f"Unknown tool {call.name!r}.")
                result = {"result": fn(**args)}
                span.update(output=result)
        except (ToolError, TypeError) as exc:  # TypeError: wrong arguments from the model
            result = {"error": str(exc)}  # the span above recorded the error; the model hears it
        return types.Part(
            function_response=types.FunctionResponse(id=call.id, name=call.name, response=result)
        )


def _part_summary(content: types.Content) -> list[str]:
    out = []
    for p in content.parts or []:
        if p.text:
            out.append(p.text[:500])
        elif p.function_response:
            out.append(f"tool result: {p.function_response.name}")
    return out
