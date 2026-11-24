from __future__ import annotations

import json
from pathlib import Path

import pytest

from srtspeak.core.speech_profiles import (
    CueSpeechProfile,
    copy_speech_styles,
    effective_tts_speed,
    load_speech_profiles,
    prepare_tts_text,
    save_speech_profiles,
    speech_profile_path,
)


def test_profile_round_trip_and_path(tmp_path: Path) -> None:
    srt = tmp_path / "dialogue.srt"
    srt.write_text("source", encoding="utf-8")
    profile = CueSpeechProfile(tts_text="Hello [pause] there", style="soft", speed=1.2)

    result = save_speech_profiles(srt, {2: profile})

    assert result == tmp_path / "dialogue.srtspeak.json"
    assert speech_profile_path(srt) == result
    assert load_speech_profiles(srt) == {2: profile}


def test_save_empty_profiles_removes_stale_sidecar(tmp_path: Path) -> None:
    srt = tmp_path / "dialogue.srt"
    srt.write_text("source", encoding="utf-8")
    save_speech_profiles(srt, {1: CueSpeechProfile(style="whisper")})

    path = save_speech_profiles(srt, {})

    assert not path.exists()
    assert load_speech_profiles(srt) == {}


def test_prepare_tts_text_applies_style_without_mutating_caption() -> None:
    caption = "Good morning (^-^)"
    profile = CueSpeechProfile(tts_text="Good morning [pause]", style="whisper")

    speech_text = prepare_tts_text(caption, profile, strip_emoticons=True)

    assert speech_text == "<whisper>Good morning [pause]</whisper>"
    assert caption == "Good morning (^-^)"


def test_effective_speed_uses_override_or_default() -> None:
    assert effective_tts_speed(None, 1.1) == 1.1
    assert effective_tts_speed(CueSpeechProfile(speed=0.8), 1.1) == 0.8


@pytest.mark.parametrize("speed", [0.69, 1.51, float("nan"), float("inf"), True])
def test_invalid_profile_speed_is_rejected(speed: float) -> None:
    with pytest.raises(ValueError, match="speed"):
        CueSpeechProfile(speed=speed).validate()


def test_invalid_style_is_rejected() -> None:
    with pytest.raises(ValueError, match="style"):
        CueSpeechProfile(style="<script>").validate()


def test_invalid_sidecar_schema_is_rejected(tmp_path: Path) -> None:
    srt = tmp_path / "dialogue.srt"
    srt.write_text("source", encoding="utf-8")
    speech_profile_path(srt).write_text(json.dumps({"schema_version": 99, "cues": {}}))

    with pytest.raises(ValueError, match="schema"):
        load_speech_profiles(srt)


def test_sidecar_is_rejected_after_srt_is_changed(tmp_path: Path) -> None:
    srt = tmp_path / "dialogue.srt"
    srt.write_text("before", encoding="utf-8")
    save_speech_profiles(srt, {1: CueSpeechProfile(style="whisper")})
    srt.write_text("after", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        load_speech_profiles(srt)


def test_copy_speech_styles_to_translated_srt_preserves_target_tts_text(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ja.srt"
    target = tmp_path / "en.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nさようなら\n",
        encoding="utf-8",
    )
    target.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nGoodbye\n",
        encoding="utf-8",
    )
    save_speech_profiles(
        source,
        {1: CueSpeechProfile(style="whisper", speed=0.85)},
    )
    save_speech_profiles(
        target,
        {
            1: CueSpeechProfile(tts_text="Hello [pause]"),
            2: CueSpeechProfile(tts_text="Farewell", style="loud", speed=1.2),
        },
    )

    copied_count = copy_speech_styles(source, target)
    target_profiles = load_speech_profiles(target)

    assert copied_count == 1
    assert target_profiles == {
        1: CueSpeechProfile(
            tts_text="Hello [pause]", style="whisper", speed=0.85
        ),
        2: CueSpeechProfile(tts_text="Farewell"),
    }


def test_copy_speech_styles_rejects_different_cue_timings(tmp_path: Path) -> None:
    source = tmp_path / "ja.srt"
    target = tmp_path / "en.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nA\n", encoding="utf-8")
    target.write_text("1\n00:00:00,000 --> 00:00:02,000\nB\n", encoding="utf-8")
    save_speech_profiles(source, {1: CueSpeechProfile(style="whisper")})

    with pytest.raises(ValueError, match="timings differ"):
        copy_speech_styles(source, target)
