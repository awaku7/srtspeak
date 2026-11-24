from __future__ import annotations

from srtspeak.cli import build_parser


def test_build_parser_accepts_tts_speed() -> None:
    args = build_parser().parse_args(
        ["build", "--srt", "clip.srt", "--tts-speed", "1.23"]
    )

    assert args.tts_speed == 1.23


def test_build_all_parser_has_global_tts_speed() -> None:
    args = build_parser().parse_args(
        ["build-all", "--map", "ja=clip.srt", "--tts-speed", "0.85"]
    )

    assert args.tts_speed == 0.85
