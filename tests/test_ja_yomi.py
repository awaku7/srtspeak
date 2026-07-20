"""Tests for Japanese kanji to hiragana (ja_yomi) via Grok Chat API (structured JSON)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from srtspeak.core.ja_yomi import (
    JaYomiError,
    apply_ja_yomi,
    convert_cues_batch,
    should_apply_ja_yomi,
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


def test_apply_ja_yomi_noop_without_api_key() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=True, lang="ja", api_key=None)
    assert out[0].text == "高野山"


def test_convert_cues_batch_success() -> None:
    cues = [
        Cue(1, 0, 1000, "高野山来ました。"),
        Cue(2, 1000, 2000, "今日はいい天気です。"),
    ]
    mock_response = {
        "cues": [
            {"index": 1, "text": "こうやさんきました。"},
            {"index": 2, "text": "きょうはいいてんきです。"},
        ]
    }
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response):
        out = convert_cues_batch(cues, "dummy-key")

    assert out[0].text == "こうやさんきました。"
    assert out[1].text == "きょうはいいてんきです。"
    assert out[0].index == 1
    assert out[1].index == 2


def test_convert_cues_batch_mismatch() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    mock_response = {"cues": [{"index": 1, "text": "こうやさん"}, {"index": 2, "text": "余分"}]}
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response):
        with pytest.raises(JaYomiError, match="returned 2 cues for 1 expected"):
            convert_cues_batch(cues, "dummy-key")


def test_convert_cues_batch_api_error() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    with patch("srtspeak.core.ja_yomi._call_chat_json", side_effect=JaYomiError("Grok Chat API error 401")):
        with pytest.raises(JaYomiError, match="Grok Chat API error 401"):
            convert_cues_batch(cues, "bad-key")


def test_build_config_ja_yomi_default_true() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    assert cfg.ja_yomi is True


def test_apply_ja_yomi_integration_via_chat() -> None:
    cues = [
        Cue(1, 0, 1000, "高野山来ました。"),
        Cue(2, 1000, 2000, "こんにちは"),
    ]
    mock_response = {
        "cues": [
            {"index": 1, "text": "こうやさんきました。"},
        ]
    }
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response):
        out = apply_ja_yomi(cues, enabled=True, lang="ja", api_key="test")

    assert "高" not in out[0].text
    assert out[1].text == "こんにちは"


def test_apply_ja_yomi_no_cache_ignores_file(tmp_path: Path) -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    work = tmp_path / "work"
    work.mkdir()
    # seed cache with wrong conversion to prove bypass
    cache_path = work / "ja_yomi_cache.json"
    import hashlib
    import json

    h = hashlib.sha256("|".join(c.text for c in cues).encode("utf-8")).hexdigest()[:16]
    cache_path.write_text(
        json.dumps({"_srt_hash": h, "1": "cached-wrong"}, ensure_ascii=False),
        encoding="utf-8",
    )
    mock_response = {"cues": [{"index": 1, "text": "こうやさん"}]}
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response) as m:
        out = apply_ja_yomi(
            cues,
            enabled=True,
            lang="ja",
            api_key="k",
            work_dir=work,
            no_cache=True,
        )
    assert m.called
    assert out[0].text == "こうやさん"

