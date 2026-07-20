"""TDD: SRT file encoding detection / fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from srtspeak.core.srt_parser import (
    SrtEncodingError,
    parse_srt,
    read_srt_text,
)


_SAMPLE = (
    "1\n"
    "00:00:07,600 --> 00:00:08,800\n"
    "行き、こんなとこ!?\n"
    "\n"
    "2\n"
    "00:00:08,800 --> 00:00:09,900\n"
    "九度山\n"
)


def test_read_srt_text_utf8(tmp_path: Path) -> None:
    path = tmp_path / "a.srt"
    path.write_bytes(_SAMPLE.encode("utf-8"))
    text, enc = read_srt_text(path)
    assert enc in ("utf-8-sig", "utf-8")
    cues = parse_srt(text)
    assert cues[0].text.startswith("行き")


def test_read_srt_text_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.srt"
    path.write_bytes(b"\xef\xbb\xbf" + _SAMPLE.encode("utf-8"))
    text, enc = read_srt_text(path)
    assert enc == "utf-8-sig"
    assert parse_srt(text)[1].text == "九度山"


def test_read_srt_text_cp932(tmp_path: Path) -> None:
    path = tmp_path / "sjis.srt"
    path.write_bytes(_SAMPLE.encode("cp932"))
    text, enc = read_srt_text(path)
    assert enc in ("cp932", "shift_jis")
    cues = parse_srt(text)
    assert cues[0].text == "行き、こんなとこ!?"
    assert cues[1].text == "九度山"


def test_read_srt_text_shift_jis_alias(tmp_path: Path) -> None:
    # shift_jis and cp932 largely overlap for this sample
    path = tmp_path / "sjis2.srt"
    path.write_bytes(_SAMPLE.encode("shift_jis"))
    text, enc = read_srt_text(path)
    assert "九度山" in text
    assert enc in ("cp932", "shift_jis", "utf-8", "utf-8-sig")


def test_read_srt_text_prefers_utf8_over_legacy(tmp_path: Path) -> None:
    """ASCII-only must stay utf-8, not be claimed as cp932."""
    sample = (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "Hello world\n"
    )
    path = tmp_path / "en.srt"
    path.write_bytes(sample.encode("ascii"))
    text, enc = read_srt_text(path)
    assert enc in ("utf-8-sig", "utf-8")
    assert "Hello world" in text


def test_read_srt_text_invalid_raises(tmp_path: Path) -> None:
    path = tmp_path / "bin.srt"
    # invalid as utf-8 and unlikely valid text srt in jp encodings as whole file
    path.write_bytes(bytes(range(256)))
    with pytest.raises(SrtEncodingError):
        read_srt_text(path)


def test_read_srt_text_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_srt_text(tmp_path / "nope.srt")
