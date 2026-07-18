"""CLI/GUI out_dir resolution: always nest under lang id."""

from __future__ import annotations

from pathlib import Path

import pytest

from srtspeak.core.util import resolve_out_dir


def test_resolve_out_dir_default_nests_lang() -> None:
    assert resolve_out_dir(None, "ja") == Path("out") / "ja"
    assert resolve_out_dir(None, "en") == Path("out") / "en"
    assert resolve_out_dir(None, "pt") == Path("out") / "pt"
    assert resolve_out_dir("", "ja") == Path("out") / "ja"


def test_resolve_out_dir_explicit_root_nests_lang() -> None:
    assert resolve_out_dir("out", "ja") == Path("out") / "ja"
    assert resolve_out_dir(Path("artifacts"), "en") == Path("artifacts") / "en"


def test_resolve_out_dir_already_ends_with_lang_not_doubled() -> None:
    """If user already passed out/ja, do not make out/ja/ja."""
    assert resolve_out_dir("out/ja", "ja") == Path("out") / "ja"
    assert resolve_out_dir(Path("out") / "pt", "pt") == Path("out") / "pt"


def test_resolve_out_dir_different_suffix_still_nests() -> None:
    """out/en with lang=ja must become out/en/ja (no strip of foreign suffix)."""
    assert resolve_out_dir("out/en", "ja") == Path("out") / "en" / "ja"


def test_resolve_out_dir_requires_lang() -> None:
    with pytest.raises(ValueError):
        resolve_out_dir("out", "")
