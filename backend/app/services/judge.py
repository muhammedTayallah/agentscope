"""LLM-as-judge: grade an agent's answer against a reference answer, 0..1 with a reason."""

import json
from typing import Any, Protocol

from app.core.config import Settings

DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "anthropic": "claude-opus-5-5"}

SYSTEM = """You grade answers from a customer-support assistant.

You get the customer's question, a reference answer written by the shop, and the \
assistant's answer. Judge whether the assistant's answer is correct and complete \
compared with the reference: same facts, numbers and dates. Wording and extra polite \
detail don't matter; wrong or missing facts do.

Score: 1.0 fully correct and complete, 0.5 partly correct or missing an important \
fact, 0.0 wrong, made up, or not an answer. Use values in between when it helps.
Give a one-sentence reason that names the missing or wrong fact, if any."""

SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}


class Judge(Protocol):
    model: str

    async def grade(self, question: str, reference: str, answer: str) -> tuple[float, str]: ...


def prompt(question: str, reference: str, answer: str) -> str:
    return (
        f"<question>\n{question}\n</question>\n\n"
        f"<reference_answer>\n{reference}\n</reference_answer>\n\n"
        f"<assistant_answer>\n{answer}\n</assistant_answer>"
    )


def parse(text: str) -> tuple[float, str]:
    data = json.loads(text)
    score = min(1.0, max(0.0, float(data["score"])))
    return score, str(data.get("reason", ""))[:1000]


class GeminiJudge:
    def __init__(self, client: Any, model: str):
        self.client, self.model = client, model

    async def grade(self, question: str, reference: str, answer: str) -> tuple[float, str]:
        from google.genai import types

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt(question, reference, answer),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_json_schema=SCHEMA,
            ),
        )
        return parse(response.text or "")


class AnthropicJudge:
    def __init__(self, client: Any, model: str):
        self.client, self.model = client, model

    async def grade(self, question: str, reference: str, answer: str) -> tuple[float, str]:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=4000,  # adaptive thinking counts against this
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt(question, reference, answer)}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if message.stop_reason == "refusal":
            raise RuntimeError("judge model declined")
        return parse(next(b.text for b in message.content if b.type == "text"))


def create_judge(settings: Settings) -> Judge | None:
    """The configured judge, or None when its provider has no API key."""
    provider = settings.judge_provider.lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unknown JUDGE_PROVIDER: {settings.judge_provider!r}")
    model = settings.judge_model or DEFAULT_MODELS[provider]
    if provider == "gemini":
        key = settings.gemini_api_key.get_secret_value()
        if not key:
            return None
        from google import genai
        from google.genai import types

        # Outlast a free-tier rate-limit window (~1 min); the SDK default gives up after ~15 s.
        retry = types.HttpRetryOptions(attempts=8, initial_delay=2.0)
        http = types.HttpOptions(retry_options=retry)
        return GeminiJudge(genai.Client(api_key=key, http_options=http), model)
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        return None
    import anthropic

    return AnthropicJudge(anthropic.AsyncAnthropic(api_key=key), model)
