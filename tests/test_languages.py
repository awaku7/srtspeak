"""Tests for language catalog and resolution."""

from __future__ import annotations

import pytest

from srtspeak.core.languages import (
    DEFAULT_LANGUAGE_CODE,
    SUPPORTED_LANGUAGE_OPTIONS,
    guess_lang_from_filename,
    internal_lang_from_code,
    resolve_language_code,
)


def test_supported_options_include_pt_variants() -> None:
    codes = {o.code for o in SUPPORTED_LANGUAGE_OPTIONS}
    assert "ja" in codes
    assert "en" in codes
    assert "pt-BR" in codes
    assert "pt-PT" in codes


def test_default_language_code_map() -> None:
    assert DEFAULT_LANGUAGE_CODE["ja"] == "ja"
    assert DEFAULT_LANGUAGE_CODE["en"] == "en"
    assert DEFAULT_LANGUAGE_CODE["pt"] == "pt-BR"


def test_guess_lang_from_filename() -> None:
    assert guess_lang_from_filename("GRAN_TENKU_japan.srt") == "ja"
    assert guess_lang_from_filename("GRAN_TENKU_English.srt") == "en"
    assert guess_lang_from_filename("GRAN_TENKU_Portugus.srt") == "pt"
    assert guess_lang_from_filename("unknown.srt") is None
    # native-script / local labels
    assert guess_lang_from_filename("GRAN_TENKU_日本語.srt") == "ja"
    assert guess_lang_from_filename("GRAN_TENKU_ไทย.srt") == "th"
    assert guess_lang_from_filename("GRAN_TENKU_中文.srt") == "zh"
    # whole-token short codes only (no false positive on tenku)
    assert guess_lang_from_filename("foo_en.srt") == "en"
    assert guess_lang_from_filename("sample-ja.srt") == "ja"
    assert guess_lang_from_filename("tenku.srt") is None


def test_resolve_explicit_overrides_default() -> None:
    assert resolve_language_code(lang="pt", explicit="pt-PT") == "pt-PT"
    assert resolve_language_code(lang="pt", explicit=None) == "pt-BR"


def test_resolve_accepts_aliases() -> None:
    assert resolve_language_code(lang="pt", explicit="pt_br") == "pt-BR"
    assert resolve_language_code(lang="ja", explicit="japanese") == "ja"


def test_resolve_unknown_raises() -> None:
    with pytest.raises(ValueError):
        resolve_language_code(lang="xx", explicit=None)
    with pytest.raises(ValueError):
        resolve_language_code(lang="ja", explicit="zz-ZZ")


def test_internal_lang_from_code() -> None:
    assert internal_lang_from_code("ja") == "ja"
    assert internal_lang_from_code("en") == "en"
    assert internal_lang_from_code("pt-BR") == "pt"
    assert internal_lang_from_code("pt-PT") == "pt"
    assert internal_lang_from_code("pt_br") == "pt"
    assert internal_lang_from_code("zh") == "zh"
    assert internal_lang_from_code("ko") == "ko"
