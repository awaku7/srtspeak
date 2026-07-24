"""CLI translate subcommand parsing."""

from __future__ import annotations

from srtspeak.cli import _parse_to_list, build_parser
from srtspeak.i18n import setup_i18n


def test_parse_to_list_repeat_and_comma() -> None:
    assert _parse_to_list(["en", "pt-BR"]) == ["en", "pt-BR"]
    assert _parse_to_list(["en,pt-BR,es"]) == ["en", "pt-BR", "es"]
    assert _parse_to_list(["en", "fr,de"]) == ["en", "fr", "de"]
    assert _parse_to_list(None) == []


def test_translate_parser_accepts_multiple_to() -> None:
    setup_i18n("en")
    p = build_parser()
    args = p.parse_args(
        [
            "translate",
            "--srt",
            "a.srt",
            "--source-lang",
            "ja",
            "--to",
            "en",
            "--to",
            "pt-BR",
            "--out",
            "out/srt_gen",
            "--dry-run",
        ]
    )
    assert args.command == "translate"
    assert args.to == ["en", "pt-BR"]
    assert args.dry_run is True


def test_translate_parser_accepts_no_cache() -> None:
    setup_i18n("en")
    p = build_parser()
    args = p.parse_args(
        [
            "translate",
            "--srt",
            "a.srt",
            "--source-lang",
            "ja",
            "--to",
            "en",
            "--out",
            "out/srt_gen",
            "--no-cache",
        ]
    )
    assert args.no_cache is True


def test_build_parser_accepts_no_cache() -> None:
    setup_i18n("en")
    p = build_parser()
    args = p.parse_args(
        [
            "build",
            "--srt",
            "a.srt",
            "--lang",
            "ja",
            "--no-cache",
        ]
    )
    assert args.no_cache is True

