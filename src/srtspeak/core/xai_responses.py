"""Small stdlib client for xAI's Responses REST API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

RESPONSES_URL = "https://api.x.ai/v1/responses"
DEFAULT_GROK_MODEL = "grok-4.7"
DEFAULT_TIMEOUT_S = 300


class ResponsesAPIError(RuntimeError):
    """xAI Responses HTTP, transport, or response-shape error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _output_text(data: dict[str, Any]) -> str:
    status = data.get("status")
    if status and status != "completed":
        reason = data.get("incomplete_details") or data.get("error") or status
        raise ResponsesAPIError(f"Responses API returned status {status}: {reason}")

    output = data.get("output")
    if not isinstance(output, list):
        raise ResponsesAPIError("Responses API response is missing output items")

    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                raise ResponsesAPIError(
                    f"Responses API refused the request: {part.get('refusal', '')}"
                )
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])

    text = "".join(text_parts).strip()
    if not text:
        raise ResponsesAPIError("Responses API response contained no assistant text")
    return text


def request_responses_text(
    *,
    api_key: str,
    model: str,
    input: str | list[dict[str, Any]],
    schema_name: str | None = None,
    schema: dict[str, Any] | None = None,
    strict: bool = True,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> str:
    """Send one non-streaming Responses request and return assistant text.

    ``store=False`` preserves the app's previous behavior of not retaining
    prompts and outputs for later retrieval on the provider's servers.
    """
    key = api_key.strip()
    if not key:
        raise ResponsesAPIError("empty api key")
    if (schema_name is None) != (schema is None):
        raise ValueError("schema_name and schema must be provided together")

    body: dict[str, Any] = {
        "model": model,
        "input": input,
        "store": False,
    }
    if schema is not None and schema_name is not None:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": bool(strict),
            }
        }
    if max_output_tokens is not None:
        body["max_output_tokens"] = int(max_output_tokens)
    if temperature is not None:
        body["temperature"] = float(temperature)

    req = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(500).decode("utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        message = f"Responses API HTTP {exc.code}"
        if detail:
            message = f"{message}: {detail}"
        raise ResponsesAPIError(message, status=int(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise ResponsesAPIError(f"Responses API network error: {exc.reason}") from exc
    except OSError as exc:
        raise ResponsesAPIError(f"Responses API network error: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResponsesAPIError(f"Responses API returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResponsesAPIError("Responses API returned a non-object JSON response")
    return _output_text(data)
