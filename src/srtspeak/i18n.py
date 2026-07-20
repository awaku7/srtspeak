"""gettext / Babel i18n helpers.

Message keys (msgid) are English. Translations live under
``srtspeak/locales/<lang>/LC_MESSAGES/srtspeak.po`` (+ compiled ``.mo``).

Locale selection order for :func:`setup_i18n` / default import:
1. explicit ``locale`` argument
2. env ``SRTSPEAK_LOCALE``
3. env ``LANG`` / ``LC_ALL`` (language part only)
4. system default locale
5. fallback ``en`` (English source strings; Japanese only when host locale is ja)
"""

from __future__ import annotations

import gettext
import locale as _locale_mod
import os
from pathlib import Path

DOMAIN = "srtspeak"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_translations: gettext.NullTranslations = gettext.NullTranslations()
_current_locale: str = "en"


def locales_dir() -> Path:
    return LOCALES_DIR


def available_locales() -> list[str]:
    """Return locale codes that have a catalog directory (plus always ``en``)."""
    found: set[str] = {"en"}
    if LOCALES_DIR.is_dir():
        for p in LOCALES_DIR.iterdir():
            if not p.is_dir():
                continue
            mo = p / "LC_MESSAGES" / f"{DOMAIN}.mo"
            po = p / "LC_MESSAGES" / f"{DOMAIN}.po"
            if mo.is_file() or po.is_file():
                found.add(p.name)
    return sorted(found)


def get_locale() -> str:
    return _current_locale


def _normalize_locale(name: str | None) -> str | None:
    if not name:
        return None
    raw = name.strip().replace("-", "_")
    if not raw or raw in {"C", "POSIX"}:
        return "en"
    # LANG often looks like ja_JP.UTF-8
    raw = raw.split(".", 1)[0]
    raw = raw.split("@", 1)[0]
    if not raw:
        return None
    primary = raw.split("_", 1)[0].lower()
    if primary in {"en", "c"}:
        return "en"
    return primary


def _detect_locale() -> str:
    for key in ("SRTSPEAK_LOCALE", "LC_ALL", "LANG"):
        norm = _normalize_locale(os.environ.get(key))
        if norm:
            return norm
    try:
        pref = _locale_mod.getlocale()[0]
    except Exception:
        pref = None
    if not pref:
        try:
            pref = _locale_mod.getdefaultlocale()[0]  # type: ignore[attr-defined]
        except Exception:
            pref = None
    norm = _normalize_locale(pref)
    if norm:
        return norm
    return "en"


def set_locale(lang: str | None) -> str:
    """Activate a locale. Returns the effective locale code.

    ``en`` uses the English source strings (explicit en catalog or identity).
    Unknown locales fall back to English source strings.
    """
    global _translations, _current_locale

    if lang is None:
        code = _detect_locale()
    else:
        code = _normalize_locale(lang) or "en"

    if code == "en":
        try:
            _translations = gettext.translation(
                DOMAIN,
                localedir=str(LOCALES_DIR),
                languages=["en"],
                fallback=False,
            )
        except FileNotFoundError:
            _translations = gettext.NullTranslations()
        _current_locale = "en"
        return _current_locale

    try:
        _translations = gettext.translation(
            DOMAIN,
            localedir=str(LOCALES_DIR),
            languages=[code],
            fallback=False,
        )
        _current_locale = code
    except FileNotFoundError:
        _translations = gettext.NullTranslations()
        _current_locale = "en"
    return _current_locale


def setup_i18n(locale: str | None = None) -> str:
    """Public alias used by CLI/GUI entrypoints."""
    return set_locale(locale)


def _(message: str) -> str:
    """gettext lookup (English msgid)."""
    return _translations.gettext(message)


def N_(message: str) -> str:
    """Mark msgid for extraction without translating at call site (noop)."""
    return message


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translations.ngettext(singular, plural, n)


# Activate default locale on import (follows host/env; English if unset).
set_locale(None)


__all__ = [
    "DOMAIN",
    "LOCALES_DIR",
    "_",
    "N_",
    "available_locales",
    "get_locale",
    "locales_dir",
    "ngettext",
    "set_locale",
    "setup_i18n",
]
