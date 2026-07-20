"""Tests for API key resolution and secure store helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from srtspeak.core.secrets import (
    api_key_status,
    clear_api_key_dpapi,
    clear_api_key_secure,
    has_api_key_dpapi,
    has_api_key_secure,
    load_api_key_dpapi,
    load_api_key_secure,
    resolve_api_key,
    save_api_key_dpapi,
    save_api_key_secure,
    secure_store_available,
)


def test_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "env-key-value")
    got = resolve_api_key(prompt=False, session_key="session-key")
    assert got == "env-key-value"


def test_session_used_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    got = resolve_api_key(
        prompt=False, session_key="session-only", use_secure_store=False
    )
    assert got == "session-only"


def test_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert (
        resolve_api_key(prompt=False, session_key=None, use_secure_store=False)
        is None
    )


def test_prompt_callable_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    calls: list[Any] = []

    def _prompt() -> str:
        calls.append(1)
        return "typed-key"

    got = resolve_api_key(
        prompt=True,
        session_key=None,
        prompt_fn=_prompt,
        use_secure_store=False,
    )
    assert got == "typed-key"
    assert calls == [1]


def test_dpapi_roundtrip_with_fake_protect(tmp_path: Path) -> None:
    store = tmp_path / "key.dpapi"

    def protect(raw: bytes) -> bytes:
        return b"P:" + raw

    def unprotect(blob: bytes) -> bytes:
        assert blob.startswith(b"P:")
        return blob[2:]

    path = save_api_key_dpapi(
        "secret-key-xyz", path=store, protect_fn=protect
    )
    assert path == store
    assert has_api_key_dpapi(path=store)
    text = store.read_text(encoding="ascii")
    assert "secret-key-xyz" not in text
    got = load_api_key_dpapi(path=store, unprotect_fn=unprotect)
    assert got == "secret-key-xyz"


def test_resolve_uses_secure_store_after_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    store = tmp_path / "key.dpapi"

    def protect(raw: bytes) -> bytes:
        return raw[::-1]

    def unprotect(blob: bytes) -> bytes:
        return blob[::-1]

    # Force keyring miss; use DPAPI path via load_api_key_secure fallback.
    monkeypatch.setattr(
        "srtspeak.core.secrets.load_api_key_keyring", lambda: None
    )
    save_api_key_dpapi("stored-key", path=store, protect_fn=protect)
    got = resolve_api_key(
        prompt=False,
        session_key=None,
        use_secure_store=True,
        dpapi_path=store,
        unprotect_fn=unprotect,
    )
    assert got == "stored-key"


def test_api_key_status_backends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    store = tmp_path / "key.dpapi"
    monkeypatch.setattr(
        "srtspeak.core.secrets.load_api_key_keyring", lambda: None
    )
    monkeypatch.setattr(
        "srtspeak.core.secrets.has_api_key_keyring", lambda: False
    )
    assert api_key_status(dpapi_path=store) == "missing"
    save_api_key_dpapi("k", path=store, protect_fn=lambda b: b)
    assert api_key_status(dpapi_path=store) == "set (dpapi)"
    monkeypatch.setenv("XAI_API_KEY", "env")
    assert api_key_status(dpapi_path=store) == "set (env)"


def test_clear_api_key_dpapi(tmp_path: Path) -> None:
    store = tmp_path / "key.dpapi"
    save_api_key_dpapi("k", path=store, protect_fn=lambda b: b)
    assert clear_api_key_dpapi(path=store) is True
    assert has_api_key_dpapi(path=store) is False
    assert clear_api_key_dpapi(path=store) is False


def test_save_api_key_secure_prefers_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("srtspeak.core.secrets.keyring_available", lambda: True)
    saved: dict[str, str] = {}

    def _save(key: str) -> None:
        saved["k"] = key

    monkeypatch.setattr("srtspeak.core.secrets.save_api_key_keyring", _save)
    monkeypatch.setattr(
        "srtspeak.core.secrets.clear_api_key_dpapi", lambda **_k: True
    )
    backend = save_api_key_secure("abc")
    assert backend == "keyring"
    assert saved["k"] == "abc"


def test_save_api_key_secure_falls_back_dpapi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("srtspeak.core.secrets.keyring_available", lambda: False)
    monkeypatch.setattr("srtspeak.core.secrets.dpapi_available", lambda: True)
    store = tmp_path / "k.dpapi"
    monkeypatch.setattr(
        "srtspeak.core.secrets.default_key_store_path", lambda: store
    )
    monkeypatch.setattr(
        "srtspeak.core.secrets._dpapi_protect", lambda raw: b"X" + raw
    )
    backend = save_api_key_secure("zz")
    assert backend == "dpapi"
    assert store.is_file()
    assert "zz" not in store.read_text(encoding="ascii")


def test_secure_store_available_true_with_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("srtspeak.core.secrets.keyring_available", lambda: True)
    assert secure_store_available() is True


def test_load_api_key_secure_keyring_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "srtspeak.core.secrets.load_api_key_keyring", lambda: "from-keyring"
    )
    monkeypatch.setattr(
        "srtspeak.core.secrets.load_api_key_dpapi",
        lambda **_k: "from-dpapi",
    )
    assert load_api_key_secure() == "from-keyring"


def test_clear_api_key_secure_both(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"k": 0, "d": 0}

    def ck() -> bool:
        calls["k"] += 1
        return True

    def cd(**_k: object) -> bool:
        calls["d"] += 1
        return False

    monkeypatch.setattr("srtspeak.core.secrets.clear_api_key_keyring", ck)
    monkeypatch.setattr("srtspeak.core.secrets.clear_api_key_dpapi", cd)
    assert clear_api_key_secure() is True
    assert calls == {"k": 1, "d": 1}


@pytest.mark.skipif(os.name != "nt", reason="real DPAPI is Windows-only")
def test_real_dpapi_roundtrip(tmp_path: Path) -> None:
    store = tmp_path / "real.dpapi"
    save_api_key_dpapi("real-secret-key", path=store)
    assert "real-secret-key" not in store.read_text(encoding="ascii")
    assert load_api_key_dpapi(path=store) == "real-secret-key"
    clear_api_key_dpapi(path=store)


@pytest.mark.skipif(
    not __import__("importlib.util").util.find_spec("keyring"),
    reason="keyring not installed",
)
def test_real_keyring_roundtrip() -> None:
    # Use a unique username to avoid clobbering a real user key during tests.
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    service = "srtspeak-test"
    user = "XAI_API_KEY_TEST"
    try:
        keyring.set_password(service, user, "test-only-key")
        assert keyring.get_password(service, user) == "test-only-key"
    except KeyringError as exc:
        pytest.skip(f"keyring backend unusable: {exc}")
    finally:
        try:
            keyring.delete_password(service, user)
        except (PasswordDeleteError, KeyringError):
            pass


def test_has_api_key_secure_or(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "srtspeak.core.secrets.has_api_key_keyring", lambda: False
    )
    monkeypatch.setattr(
        "srtspeak.core.secrets.has_api_key_dpapi", lambda **_k: True
    )
    assert has_api_key_secure() is True
