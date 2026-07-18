"""Tests for xAI Grok TTS client (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from srtspeak.core.tts_xai import (
    API_BASE,
    TtsError,
    build_tts_request_body,
    fetch_voices,
    synthesize_to_file,
)


def test_api_base_hardcoded() -> None:
    assert API_BASE == "https://api.x.ai/v1"


def test_build_tts_request_body_fixed_fields() -> None:
    body = build_tts_request_body(
        text="hello",
        voice_id="Leo",
        language_code="ja",
        sample_rate=24000,
        codec="wav",
        tts_speed=1.0,
        text_normalization=True,
    )
    assert body["text"] == "hello"
    assert body["voice_id"] == "leo"
    assert body["language"] == "ja"
    assert body["speed"] == 1.0
    assert body["text_normalization"] is True
    assert body["output_format"] == {"codec": "wav", "sample_rate": 24000}
    assert "with_timestamps" not in body
    assert "model" not in body


def test_build_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_tts_request_body(
            text="  ",
            voice_id="leo",
            language_code="ja",
            sample_rate=24000,
            codec="wav",
            tts_speed=1.0,
            text_normalization=True,
        )


def test_build_rejects_over_15k() -> None:
    with pytest.raises(ValueError, match="15000"):
        build_tts_request_body(
            text="a" * 15_001,
            voice_id="leo",
            language_code="ja",
            sample_rate=24000,
            codec="wav",
            tts_speed=1.0,
            text_normalization=True,
        )


def test_synthesize_writes_raw_bytes(tmp_path: Path) -> None:
    out = tmp_path / "out.wav"
    fake_audio = b"RIFF" + b"\x00" * 40

    class _Resp:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return fake_audio

        def getcode(self) -> int:
            return 200

        def headers(self) -> dict[str, str]:  # type: ignore[override]
            return {"Content-Type": "audio/wav"}

    with patch("srtspeak.core.tts_xai.urllib.request.urlopen", return_value=_Resp()):
        path, meta = synthesize_to_file(
            text="hi",
            voice_id="leo",
            language_code="ja",
            api_key="test-key",
            out_path=out,
            sample_rate=24000,
            codec="wav",
            tts_speed=1.0,
            text_normalization=True,
        )
    assert path == out
    assert out.read_bytes() == fake_audio
    assert meta["status"] == 200
    assert meta["bytes"] == len(fake_audio)


def test_synthesize_401_raises_no_retry(tmp_path: Path) -> None:
    import urllib.error

    out = tmp_path / "out.wav"
    err = urllib.error.HTTPError(
        url="https://api.x.ai/v1/tts",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with patch("srtspeak.core.tts_xai.urllib.request.urlopen", side_effect=err):
        with pytest.raises(TtsError, match="401"):
            synthesize_to_file(
                text="hi",
                voice_id="leo",
                language_code="ja",
                api_key="bad",
                out_path=out,
            )


def test_fetch_voices_parses_list() -> None:
    payload = {
        "voices": [
            {"voice_id": "Leo", "name": "Leo", "description": "Authoritative"},
            {"voice_id": "eve", "name": "Eve", "description": "Upbeat"},
        ]
    }
    raw = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return raw

        def getcode(self) -> int:
            return 200

    with patch("srtspeak.core.tts_xai.urllib.request.urlopen", return_value=_Resp()):
        voices = fetch_voices(api_key="k")
    assert voices[0].voice_id == "leo"
    assert voices[1].voice_id == "eve"
    assert len(voices) == 2
