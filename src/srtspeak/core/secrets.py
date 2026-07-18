"""API key resolution. Never log or persist the value."""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable


def resolve_api_key(
    *,
    prompt: bool = False,
    session_key: str | None = None,
    prompt_fn: Callable[[], str] | None = None,
    env_name: str = "XAI_API_KEY",
) -> str | None:
    """Resolve API key: env > session > optional prompt.

    Does not read .env files. Does not write anywhere.
    """
    env_val = os.environ.get(env_name)
    if env_val is not None and env_val.strip():
        return env_val.strip()
    if session_key is not None and session_key.strip():
        return session_key.strip()
    if prompt:
        fn = prompt_fn or (lambda: getpass.getpass("XAI_API_KEY: "))
        typed = fn()
        if typed is not None and typed.strip():
            return typed.strip()
    return None


def api_key_status() -> str:
    """Return presence only: 'set (env)' or 'missing'."""
    val = os.environ.get("XAI_API_KEY")
    if val is not None and val.strip():
        return "set (env)"
    return "missing"
