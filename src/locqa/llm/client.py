"""LLM clients behind one small interface, so the provider changes with a flag and tests
run without network or money."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from locqa.errors import LLMError


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, schema: dict) -> LLMResponse: ...


def load_env() -> None:
    """Read .env from the working directory if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


class GeminiClient:
    """Google Gemini via google-genai: temperature 0, JSON output constrained by a schema."""

    def __init__(self, model: str, api_key: str | None = None, retries: int = 4) -> None:
        load_env()
        api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key or api_key.startswith("ВСТАВЬТЕ"):
            raise LLMError(
                "нет ключа: получите его на https://aistudio.google.com/apikey "
                "и впишите в .env строкой GEMINI_API_KEY=..."
            )
        # Free tier allows a few requests per minute: space requests out (0 = no pacing).
        rpm = float(os.environ.get("LOCQA_LLM_RPM") or 0)
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._last_request = 0.0
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMError('не установлен google-genai: pip install -e ".[llm]"') from e
        self._client = genai.Client(api_key=api_key)
        self._types = types
        self.model = model
        self.retries = retries

    def complete(self, system: str, user: str, schema: dict) -> LLMResponse:
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=user, config=config
                )
                usage = response.usage_metadata
                return LLMResponse(
                    text=response.text or "",
                    input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                    # Thinking tokens are billed as output.
                    output_tokens=(
                        (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                        if usage
                        else 0
                    ),
                )
            except Exception as e:  # network, quota, server errors
                last_error = e
                message = str(e)
                if any(s in message for s in ("API_KEY_INVALID", "PERMISSION_DENIED", "NOT_FOUND")):
                    break  # retrying will not help
                if attempt < self.retries:
                    # A rate limit (429) needs a real pause; other errors a short one.
                    rate_limited = "429" in message or "RESOURCE_EXHAUSTED" in message
                    if rate_limited and "per day" in message.lower():
                        break  # daily quota is gone until tomorrow
                    time.sleep(20 * (attempt + 1) if rate_limited else 2**attempt)
        raise LLMError(f"запрос к {self.model} не удался: {_short(last_error)}")


def _short(error: Exception | None, limit: int = 400) -> str:
    text = " ".join(str(error).split())
    return text if len(text) <= limit else text[:limit] + "…"


class FakeClient:
    """Test double: `responder(system, user) -> JSON text`; counts tokens by characters."""

    def __init__(self, responder: Callable[[str, str], str], model: str = "fake") -> None:
        self.responder = responder
        self.model = model
        self.calls: list[str] = []

    def complete(self, system: str, user: str, schema: dict) -> LLMResponse:
        self.calls.append(user)
        text = self.responder(system, user)
        return LLMResponse(
            text=text, input_tokens=len(system + user) // 4, output_tokens=len(text) // 4
        )


def make_client(model: str) -> LLMClient:
    if model.startswith("gemini"):
        return GeminiClient(model)
    raise LLMError(f"неизвестный провайдер для модели '{model}': поддерживается gemini-*")
