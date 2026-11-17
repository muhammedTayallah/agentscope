"""Ask the demo support agent one question, traced to AgentScope.

    uv run python -m agentscope_evals "Where is my order A1002?"

Needs GEMINI_API_KEY (the agent) and AGENTSCOPE_API_KEY (+ AGENTSCOPE_HOST) for tracing.
"""

import argparse
import os
import sys
from pathlib import Path

from agentscope_sdk import AgentScope

from agentscope_evals.agent import DEFAULT_MODEL, SupportAgent, gemini_client

ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AGENTSCOPE_API_KEY", "AGENTSCOPE_HOST")


def load_env(path: Path) -> None:
    """Take the agent's keys from the repo .env; variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in ENV_KEYS and not os.environ.get(key.strip()):
            os.environ[key.strip()] = value.strip().strip("'\"")


def main() -> int:
    load_env(Path(__file__).resolve().parents[3] / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--version", default="v1", help="Recorded as agent_version on the trace")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        print("Set GEMINI_API_KEY to run the agent.", file=sys.stderr)
        return 2

    scope = AgentScope()
    agent = SupportAgent(gemini_client(), scope, model=args.model, version=args.version)
    try:
        result = agent.run(args.question)
    except Exception as exc:  # the failed run is already traced; keep the CLI output short
        print(f"Agent failed: {type(exc).__name__}: {exc}"[:500], file=sys.stderr)
        return 1
    finally:
        scope.flush()
    print(result.answer)
    print(
        f"\n[trace {result.trace_id} | {result.steps} model calls | tools: "
        f"{', '.join(result.tool_calls) or 'none'}]",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
