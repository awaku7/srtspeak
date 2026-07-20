"""API key resolution and OS credential-store persistence.

Priority: env ``XAI_API_KEY`` > session > keyring > DPAPI file (Windows legacy)
> optional prompt.

Plaintext keys are never written to gui_settings, reports, or logs.

Backends:
- **keyring** (preferred): Windows Credential Locker, macOS Keychain,
  Linux Secret Service / KWallet (via the ``keyring`` package)
- **DPAPI file** (Windows fallback / migration):
  ``%LOCALAPPDATA%\\srtspeak\\xai_api_key.dpapi``
"""

from __future__ import annotations

import base64
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

_ENV_NAME = "XAI_API_KEY"
_KEYRING_SERVICE = "srtspeak"
_KEYRING_USERNAME = "XAI_API_KEY"
_STORE_FILENAME = "xai_api_key.dpapi"
_STORE_DIRNAME = "srtspeak"


# ----- paths / availability -------------------------------------------------

def default_key_store_path() -> Path:
    """Legacy DPAPI file path (Windows). Kept for migration/clear."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / _STORE_DIRNAME / _STORE_FILENAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / _STORE_DIRNAME / _STORE_FILENAME
    return Path.home() / f".{_STORE_DIRNAME}" / _STORE_FILENAME


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
    except Exception:
        return False
    return True


def dpapi_available() -> bool:
    """True when Windows DPAPI file backend can run."""
    return sys.platform == "win32"


def secure_store_available() -> bool:
    """True if any persistent secure backend can save keys."""
    return keyring_available() or dpapi_available()


def secure_store_backend_label() -> str:
    """Short label for UI (no secrets)."""
    if keyring_available():
        try:
            import keyring

            backend = keyring.get_keyring()
            name = type(backend).__name__
            return f"keyring:{name}"
        except Exception:
            return "keyring"
    if dpapi_available():
        return "dpapi"
    return "none"


# ----- keyring --------------------------------------------------------------

def save_api_key_keyring(key: str) -> None:
    text = (key or "").strip()
    if not text:
        raise ValueError("api key is empty")
    if not keyring_available():
        raise OSError("keyring package is not available")
    import keyring
    from keyring.errors import KeyringError

    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, text)
    except KeyringError as exc:
        raise OSError(f"keyring set_password failed: {exc}") from exc


def load_api_key_keyring() -> str | None:
    if not keyring_available():
        return None
    import keyring
    from keyring.errors import KeyringError

    try:
        val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except KeyringError:
        return None
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def clear_api_key_keyring() -> bool:
    """Delete keyring entry. True if delete was attempted successfully."""
    if not keyring_available():
        return False
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    try:
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        return True
    except PasswordDeleteError:
        return False
    except KeyringError:
        return False


def has_api_key_keyring() -> bool:
    return load_api_key_keyring() is not None


# ----- DPAPI file (Windows legacy) ------------------------------------------

def _dpapi_protect(raw: bytes) -> bytes:
    if not dpapi_available():
        raise OSError("DPAPI is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    in_buf = ctypes.create_string_buffer(raw)
    in_blob = DATA_BLOB(len(raw), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "srtspeak XAI_API_KEY",
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    ):
        raise OSError(f"CryptProtectData failed: {ctypes.GetLastError()}")

    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
    return protected


def _dpapi_unprotect(protected: bytes) -> bytes:
    if not dpapi_available():
        raise OSError("DPAPI is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    in_buf = ctypes.create_string_buffer(protected)
    in_blob = DATA_BLOB(
        len(protected), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char))
    )
    out_blob = DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    ):
        raise OSError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")

    try:
        raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
    return raw


def save_api_key_dpapi(
    key: str,
    *,
    path: Path | None = None,
    protect_fn: Callable[[bytes], bytes] | None = None,
) -> Path:
    """Encrypt and store API key via DPAPI file. Returns store path."""
    text = (key or "").strip()
    if not text:
        raise ValueError("api key is empty")
    store = Path(path) if path is not None else default_key_store_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    fn = protect_fn or _dpapi_protect
    blob = fn(text.encode("utf-8"))
    store.write_text(base64.b64encode(blob).decode("ascii") + "\n", encoding="ascii")
    try:
        os.chmod(store, 0o600)
    except OSError:
        pass
    return store


def load_api_key_dpapi(
    *,
    path: Path | None = None,
    unprotect_fn: Callable[[bytes], bytes] | None = None,
) -> str | None:
    store = Path(path) if path is not None else default_key_store_path()
    if not store.is_file():
        return None
    try:
        b64 = store.read_text(encoding="ascii").strip()
        if not b64:
            return None
        blob = base64.b64decode(b64.encode("ascii"))
        fn = unprotect_fn or _dpapi_unprotect
        raw = fn(blob)
        text = raw.decode("utf-8").strip()
        return text or None
    except (OSError, ValueError, UnicodeError):
        return None


def clear_api_key_dpapi(*, path: Path | None = None) -> bool:
    store = Path(path) if path is not None else default_key_store_path()
    try:
        if store.is_file():
            store.unlink()
            return True
    except OSError:
        return False
    return False


def has_api_key_dpapi(*, path: Path | None = None) -> bool:
    store = Path(path) if path is not None else default_key_store_path()
    return store.is_file() and store.stat().st_size > 0


# ----- unified secure store -------------------------------------------------

def save_api_key_secure(key: str) -> str:
    """Save key to the best available backend.

    Returns a short backend id: ``keyring`` or ``dpapi``.
    Prefers keyring; on success also removes legacy DPAPI file if present.
    """
    text = (key or "").strip()
    if not text:
        raise ValueError("api key is empty")

    if keyring_available():
        save_api_key_keyring(text)
        # Migrate off legacy file so only one store remains.
        clear_api_key_dpapi()
        return "keyring"

    if dpapi_available():
        save_api_key_dpapi(text)
        return "dpapi"

    raise OSError(
        "No secure store available. Install the keyring package "
        "(pip install keyring), or set XAI_API_KEY in the environment."
    )


def load_api_key_secure(
    *,
    dpapi_path: Path | None = None,
    unprotect_fn: Callable[[bytes], bytes] | None = None,
) -> str | None:
    """Load key: keyring first, then legacy DPAPI file."""
    got = load_api_key_keyring()
    if got:
        return got
    return load_api_key_dpapi(path=dpapi_path, unprotect_fn=unprotect_fn)


def clear_api_key_secure(*, dpapi_path: Path | None = None) -> bool:
    """Clear keyring and/or DPAPI stores. True if anything was removed."""
    removed = False
    if clear_api_key_keyring():
        removed = True
    if clear_api_key_dpapi(path=dpapi_path):
        removed = True
    return removed


def has_api_key_secure(*, dpapi_path: Path | None = None) -> bool:
    if has_api_key_keyring():
        return True
    return has_api_key_dpapi(path=dpapi_path)


def resolve_api_key(
    *,
    prompt: bool = False,
    session_key: str | None = None,
    prompt_fn: Callable[[], str] | None = None,
    env_name: str = _ENV_NAME,
    use_secure_store: bool = True,
    # backward-compatible aliases
    use_dpapi: bool | None = None,
    dpapi_path: Path | None = None,
    unprotect_fn: Callable[[bytes], bytes] | None = None,
) -> str | None:
    """Resolve API key: env > session > secure store > optional prompt.

    Does not read .env files. Does not write anywhere (except via explicit save_*).
    """
    if use_dpapi is not None:
        use_secure_store = use_dpapi

    env_val = os.environ.get(env_name)
    if env_val is not None and env_val.strip():
        return env_val.strip()
    if session_key is not None and session_key.strip():
        return session_key.strip()
    if use_secure_store:
        stored = load_api_key_secure(
            dpapi_path=dpapi_path, unprotect_fn=unprotect_fn
        )
        if stored:
            return stored
    if prompt:
        fn = prompt_fn or (lambda: getpass.getpass("XAI_API_KEY: "))
        typed = fn()
        if typed is not None and typed.strip():
            return typed.strip()
    return None


def api_key_status(
    *,
    env_name: str = _ENV_NAME,
    dpapi_path: Path | None = None,
) -> str:
    """Presence only: set (env) / set (keyring) / set (dpapi) / missing."""
    val = os.environ.get(env_name)
    if val is not None and val.strip():
        return "set (env)"
    if has_api_key_keyring():
        return "set (keyring)"
    if has_api_key_dpapi(path=dpapi_path):
        return "set (dpapi)"
    return "missing"
