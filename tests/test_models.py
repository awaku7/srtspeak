"""Tests for BuildConfig and related models."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from srtspeak.core.models import BuildConfig


def test_build_config_has_no_api_key_field() -> None:
    names = {f.name for f in fields(BuildConfig)}
    assert "api_key" not in names


def test_build_config_defaults() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    assert cfg.provider == "xai_grok"
    assert cfg.voice_id == "leo"
    assert cfg.sample_rate == 24000
    assert cfg.codec == "wav"
    assert cfg.tts_speed == 1.0
    assert cfg.text_normalization is True
    assert cfg.fit == "force"
    assert cfg.short_mode == "pad"
    assert cfg.jobs == 1
    assert cfg.dry_run is False
    assert cfg.also_mp3 is False


def test_build_config_is_frozen() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    with pytest.raises(Exception):
        cfg.voice_id = "eve"  # type: ignore[misc]


def test_jobs_must_be_one_on_validate() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
        jobs=2,
    )
    with pytest.raises(ValueError, match="jobs"):
        cfg.validate()


def test_build_config_no_cache_default_false() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    assert cfg.no_cache is False


def test_build_config_no_cache_field_present() -> None:
    names = {f.name for f in fields(BuildConfig)}
    assert "no_cache" in names

