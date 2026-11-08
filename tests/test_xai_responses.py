"""Tests for the shared xAI Responses REST client."""

from __future__ import annotations

import json
from typing import Self
from unittest.mock import patch

import pytest

from srtspeak.core.xai_responses import (
    DEFAULT_GROK_MODEL,
    RESPONSES_URL,
    ResponsesAPIError,
    _output_text,
    request_responses_text,
)


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_responses_rest_payload_and_structured_text_extraction() -> None:
    captured: dict[str, object] = {}
    api_response = {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": '{"cues":[]}'}],
            },
        ],
    }

    def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _Response(api_response)

    with patch("srtspeak.core.xai_responses.urllib.request.urlopen", fake_urlopen):
        text = request_responses_text(
            api_key="secret-test-key",
            model=DEFAULT_GROK_MODEL,
            input=[{"role": "user", "content": "translate"}],
            schema_name="translated_cues",
            schema={"type": "object", "properties": {"cues": {"type": "array"}}},
            strict=True,
            max_output_tokens=1234,
            temperature=0.2,
            timeout=17,
        )

    assert text == '{"cues":[]}'
    assert captured["url"] == RESPONSES_URL
    assert captured["authorization"] == "Bearer secret-test-key"
    assert captured["timeout"] == 17
    body = captured["body"]
    assert body["model"] == "grok-4.7"
    assert body["input"] == [{"role": "user", "content": "translate"}]
    assert body["store"] is False
    assert body["max_output_tokens"] == 1234
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "translated_cues"
    assert body["text"]["format"]["strict"] is True


def test_responses_client_rejects_incomplete_and_refusal() -> None:
    with pytest.raises(ResponsesAPIError, match="status incomplete"):
        _output_text({"status": "incomplete", "output": []})

    with pytest.raises(ResponsesAPIError, match="refused"):
        _output_text(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "refusal", "refusal": "not allowed"}],
                    }
                ],
            }
        )


def test_responses_client_requires_key_and_paired_schema_arguments() -> None:
    with pytest.raises(ResponsesAPIError, match="empty api key"):
        request_responses_text(api_key=" ", model="grok-4.7", input="hello")

    with pytest.raises(ValueError, match="provided together"):
        request_responses_text(
            api_key="key", model="grok-4.7", input="hello", schema_name="incomplete"
        )
