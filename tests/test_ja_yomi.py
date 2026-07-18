"""Tests for Japanese kanji to hiragana (kanjiconv) preprocessing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from srtspeak.core.ja_yomi import (
    JaYomiError,
    apply_ja_yomi,
    kanjiconv_available,
    should_apply_ja_yomi,
    to_hiragana,
)
from srtspeak.core.models import BuildConfig
from srtspeak.core.srt_parser import Cue


def test_should_apply_only_for_ja() -> None:
    assert should_apply_ja_yomi(enabled=True, lang="ja") is True
    assert should_apply_ja_yomi(enabled=True, lang="en") is False
    assert should_apply_ja_yomi(enabled=False, lang="ja") is False


def test_apply_ja_yomi_noop_when_disabled() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=False, lang="ja")
    assert out[0].text == "高野山"


def test_apply_ja_yomi_noop_for_en() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=True, lang="en")
    assert out[0].text == "高野山"


@pytest.mark.skipif(not kanjiconv_available(), reason="kanjiconv not installed")
def test_to_hiragana_converts_kanji() -> None:
    out = to_hiragana("高野山")
    assert out
    assert "高" not in out
    assert "野" not in out
    assert "山" not in out
    assert any("\u3040" <= ch <= "\u309f" for ch in out)


@pytest.mark.skipif(not kanjiconv_available(), reason="kanjiconv not installed")
def test_apply_ja_yomi_replaces_cue_text() -> None:
    cues = [
        Cue(1, 0, 1000, "高野山 来ました。"),
        Cue(2, 1000, 2000, "こんにちは"),
    ]
    out = apply_ja_yomi(cues, enabled=True, lang="ja")
    assert out[0].index == 1
    assert out[0].start_ms == 0
    assert "高" not in out[0].text
    assert out[1].text


def test_to_hiragana_missing_kanjiconv_raises() -> None:
    import srtspeak.core.ja_yomi as mod

    mod._get_converter.cache_clear()
    real_import = __import__

    def _boom(name: str, *args: Any, **kwargs: Any):
        if name == "kanjiconv" or name.startswith("kanjiconv."):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_boom):
        mod._get_converter.cache_clear()
        with pytest.raises(JaYomiError, match="kanjiconv"):
            to_hiragana("山")
    mod._get_converter.cache_clear()


def test_build_config_ja_yomi_default_true() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    assert cfg.ja_yomi is True


def test_empty_to_hiragana() -> None:
    if not kanjiconv_available():
        pytest.skip("kanjiconv not installed")
    assert to_hiragana("") == ""