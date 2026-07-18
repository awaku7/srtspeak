"""Tests for SRT parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from srtspeak.core.srt_parser import (
    Cue,
    SrtParseError,
    parse_srt,
    parse_timestamp_ms,
)
from srtspeak.i18n import get_locale, set_locale


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _force_ja_locale():
    """SRT anomaly tests assert Japanese user-facing strings."""
    prev = get_locale()
    set_locale("ja")
    yield
    set_locale(prev)



def test_parse_timestamp_ms() -> None:
    assert parse_timestamp_ms("00:00:07,600") == 7600
    assert parse_timestamp_ms("00:12:44,000") == 764_000
    assert parse_timestamp_ms("01:02:03.456") == 3_723_456


def test_parse_timestamp_ms_invalid_japanese() -> None:
    with pytest.raises(SrtParseError) as ei:
        parse_timestamp_ms("not-a-time")
    msg = str(ei.value)
    assert "タイムスタンプ" in msg
    assert "not-a-time" in msg


def test_parse_sample_block() -> None:
    text = (
        "1\n"
        "00:00:07,600 --> 00:00:08,800\n"
        "行き、こんなとこ!?\n"
        "\n"
        "2\n"
        "00:00:08,800 --> 00:00:09,900\n"
        "九度山\n"
    )
    cues = parse_srt(text)
    assert len(cues) == 2
    assert cues[0] == Cue(
        index=1,
        start_ms=7600,
        end_ms=8800,
        text="行き、こんなとこ!?",
    )
    assert cues[0].window_ms == 1200
    assert cues[1].text == "九度山"


def test_parse_rejects_empty_text() -> None:
    text = "1\n00:00:00,000 --> 00:00:01,000\n\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "空" in msg
    assert "1" in msg


def test_parse_rejects_inverted_times() -> None:
    text = "1\n00:00:02,000 --> 00:00:01,000\nhello\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "終了" in msg or "開始" in msg or "長さ" in msg
    assert "1" in msg


def test_parse_rejects_zero_duration() -> None:
    text = "1\n00:00:01,000 --> 00:00:01,000\nhello\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "長さ" in msg or "終了" in msg


def test_parse_rejects_overlap() -> None:
    text = (
        "1\n00:00:00,000 --> 00:00:02,000\na\n\n"
        "2\n00:00:01,000 --> 00:00:03,000\nb\n"
    )
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "重な" in msg
    assert "1" in msg and "2" in msg


def test_parse_rejects_invalid_index() -> None:
    text = "abc\n00:00:00,000 --> 00:00:01,000\nhello\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    assert "番号" in str(ei.value)


def test_parse_rejects_missing_timing() -> None:
    text = "1\nhello only\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    # either missing timing or invalid timing line
    assert "タイミング" in msg or "時刻" in msg


def test_parse_rejects_invalid_timing_arrow() -> None:
    text = "1\n00:00:00,000 -> 00:00:01,000\nhello\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "タイミング" in msg or "時刻" in msg


def test_parse_rejects_empty_file() -> None:
    with pytest.raises(SrtParseError) as ei:
        parse_srt("")
    assert "キュー" in str(ei.value) or "見つかり" in str(ei.value)


def test_parse_rejects_text_too_long() -> None:
    body = "x" * 15_001
    text = f"1\n00:00:00,000 --> 00:00:01,000\n{body}\n"
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "15000" in msg or "文字" in msg


def test_parse_collects_multiple_issues() -> None:
    """複数キューの異常をまとめて日本語で報告する。"""
    text = (
        "1\n00:00:02,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n\n\n"
        "3\n00:00:03,500 --> 00:00:05,000\nworld\n"
    )
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    err = ei.value
    assert isinstance(err, SrtParseError)
    assert len(err.issues) >= 2
    joined = "\n".join(err.issues)
    assert "1" in joined  # inverted
    assert "2" in joined  # empty text
    # overall message is Japanese
    assert "SRT" in str(err) or "解析" in str(err) or "問題" in str(err)


def test_parse_real_ja_srt() -> None:
    path = ROOT / "GRAN_TENKU_japan.srt"
    cues = parse_srt(path.read_text(encoding="utf-8-sig"))
    assert len(cues) == 293
    assert cues[0].index == 1
    assert cues[0].start_ms == 7600
    assert cues[-1].end_ms == 764_000


def test_window_is_half_open() -> None:
    c = Cue(index=1, start_ms=1000, end_ms=2000, text="x")
    assert c.window_ms == 1000


def test_srt_parse_error_is_value_error() -> None:
    assert issubclass(SrtParseError, ValueError)
