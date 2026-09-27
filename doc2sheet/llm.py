"""A tiny client for any OpenAI-compatible chat-completions API.

One code path covers Hugging Face Inference Providers, OpenAI, Google Gemini's
OpenAI endpoint, OpenRouter, Groq, a local Ollama server, vLLM, LM Studio...

Structured-output support differs between providers, so ``json_mode="auto"``
starts with a strict JSON schema and quietly downgrades (schema -> json_object
-> plain prompt) when a provider rejects the ``response_format`` parameter.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from doc2sheet.config import Settings

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
JSON_MODES = ("auto", "schema", "object", "off")


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMClient(Protocol):
    """Anything that can turn chat messages into a text reply."""

    model: str

    def complete(self, messages: list[dict[str, Any]], *, json_schema: dict | None = None) -> str: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        json_mode: str = "auto",
        timeout: float = 120.0,
        max_retries: int = 3,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if json_mode not in JSON_MODES:
            raise ValueError(f"json_mode must be one of {JSON_MODES}, got {json_mode!r}")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.json_mode = json_mode
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        # e.g. "none" turns thinking off on Ollama; left out of the request when unset
        self.reasoning_effort = reasoning_effort
        self._sleep = sleep
        self._resolved_mode: str | None = None  # remembered after "auto" finds what works
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> OpenAICompatibleClient:
        params: dict[str, Any] = dict(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            json_mode=settings.json_mode,
            timeout=settings.timeout,
            reasoning_effort=settings.reasoning_effort,
        )
        params.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**params)

    def close(self) -> None:
        self._http.close()

    # -- public API ---------------------------------------------------------

    def complete(self, messages: list[dict[str, Any]], *, json_schema: dict | None = None) -> str:
        modes = self._modes_to_try(json_schema)
        last_error: ProviderError | None = None
        for mode in modes:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort
            if mode == "schema" and json_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "extracted_document", "schema": json_schema, "strict": True},
                }
            elif mode == "object":
                payload["response_format"] = {"type": "json_object"}

            try:
                data = self._post(payload)
            except ProviderError as exc:
                # 400/422 usually means "this provider doesn't support response_format".
                if self.json_mode == "auto" and exc.status_code in (400, 422) and mode != modes[-1]:
                    last_error = exc
                    continue
                raise
            self._resolved_mode = mode
            return _message_text(data)
        raise last_error or ProviderError("No request was made")

    # -- internals ----------------------------------------------------------

    def _modes_to_try(self, json_schema: dict | None) -> list[str]:
        if self.json_mode != "auto":
            return [self.json_mode]
        if self._resolved_mode:
            return [self._resolved_mode]
        return ["schema", "object", "off"] if json_schema is not None else ["object", "off"]

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.post(url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < self.max_retries:
                    self._sleep(_backoff(attempt))
                    continue
                raise ProviderError(f"Could not reach {self.base_url}: {exc}") from exc

            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                self._sleep(_retry_after(response) or _backoff(attempt))
                continue
            if response.status_code >= 400:
                raise ProviderError(_explain(response, self.model, self.base_url), response.status_code)
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(f"Provider returned non-JSON: {response.text[:200]}") from exc
        raise ProviderError("Retries exhausted")  # pragma: no cover - loop always returns/raises


def _message_text(data: dict[str, Any]) -> str:
    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderError(f"Unexpected response shape: {str(data)[:200]}") from exc
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not content:
        # Reasoning ("thinking") models can spend the whole token budget before answering.
        if message.get("reasoning") or message.get("reasoning_content") or choice.get("finish_reason") == "length":
            raise ProviderError(
                "The model used its whole output budget thinking and returned no answer. Use a non-thinking "
                "model (e.g. an '-instruct' variant), give it a larger context window, or try "
                "DOC2SHEET_REASONING_EFFORT=none (only some models honour it)."
            )
        raise ProviderError("The model returned an empty response")
    return content


def _backoff(attempt: int) -> float:
    return min(2.0**attempt, 20.0)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return min(float(value), 20.0) if value else None
    except ValueError:
        return None


def _explain(response: httpx.Response, model: str, base_url: str) -> str:
    status = response.status_code
    body = response.text[:300].strip()
    if status in (401, 403):
        return (
            f"Authentication failed ({status}). Check your API key. For Hugging Face, use a token "
            "with the 'Make calls to Inference Providers' permission."
        )
    if status == 402:
        return "The provider says you are out of credits (402). Add credits or switch provider/model."
    if status == 404:
        return f"Model '{model}' was not found at {base_url} (404). Check the model id or pick another model."
    if status == 413:
        return "Request too large (413). Try fewer pages or a smaller image."
    return f"Provider error {status}: {body}"
