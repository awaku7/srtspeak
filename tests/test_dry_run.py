"""Tests for dry-run cost estimate and report shape."""

from __future__ import annotations

from pathlib import Path

from srtspeak.core.models import BuildConfig
from srtspeak.core.pipeline import dry_run_build
from srtspeak.core.report import estimate_cost_usd


ROOT = Path(__file__).resolve().parents[1]


def test_estimate_cost_usd() -> None:
    # $15 / 1M chars
    assert estimate_cost_usd(1_000_000) == 15.0
    assert estimate_cost_usd(1000) == 0.015


def test_dry_run_on_real_srt(tmp_path: Path) -> None:
    cfg = BuildConfig(
        srt_path=ROOT / "GRAN_TENKU_japan.srt",
        lang="ja",
        language_code="ja",
        out_dir=tmp_path / "out",
        dry_run=True,
        limit=5,
    )
    report = dry_run_build(cfg)
    assert report["status"] == "dry_run"
    assert report["lang"] == "ja"
    assert report["language_code"] == "ja"
    assert report["voice_id"] == "leo"
    assert report["provider"] == "xai_grok"
    assert report["cue_count"] == 5
    assert report["processed_count"] == 5
    assert "api_key" not in report
    assert "XAI_API_KEY" not in str(report)
    assert len(report["cues"]) == 5
    assert report["cues"][0]["index"] == 1
    assert report["cues"][0]["window_ms"] == 1200
    assert report["cues"][0]["text_chars"] > 0
    assert report["estimated_cost_usd"] > 0
    assert report["cues"][0].get("raw_duration_ms") is None
    assert report["ja_yomi"] is True
