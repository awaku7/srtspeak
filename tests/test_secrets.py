"""Tests for API key resolution (no persistence)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from srtspeak.core.secrets import resolve_api_key


def test_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "env-key-value")
    got = resolve_api_key(prompt=False, session_key="session-key")
    assert got == "env-key-value"


def test_session_used_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    got = resolve_api_key(prompt=False, session_key="session-only")
    assert got == "session-only"


def test_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert resolve_api_key(prompt=False, session_key=None) is None


def test_prompt_callable_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    calls: list[Any] = []

    def _prompt() -> str:
        calls.append(1)
        return "typed-key"

    got = resolve_api_key(prompt=True, session_key=None, prompt_fn=_prompt)
    assert got == "typed-key"
    assert calls == [1]
