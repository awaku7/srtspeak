"""Pipeline e2e with mocked TTS (no live API)."""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from srtspeak.core.cancel import BuildCancelled, CancellationToken
from srtspeak.core.models import BuildConfig
from srtspeak.core.pipeline import BuildService, run_build
from srtspeak.core.report import track_filename
from srtspeak.core.util import ms_to_samples, wav_duration_ms


def _write_pcm_wav(path: Path, duration_ms: int, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = ms_to_samples(duration_ms, sample_rate)
    frames = b"".join(
        struct.pack("<h", 1000 if i % 2 == 0 else -1000) for i in range(n)
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)


def _minimal_srt(path: Path) -> None:
    # two cues, 1000ms each, non-overlapping
    path.write_text(
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "こんにちは\n"
        "\n"
        "2\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "世界\n"
        "\n",
        encoding="utf-8",
    )


def _fake_synthesize(
    *,
    text: str,
    voice_id: str,
    language_code: str,
    api_key: str,
    out_path: Path,
    sample_rate: int = 24000,
    codec: str = "wav",
    tts_speed: float = 1.0,
    text_normalization: bool = True,
    **kwargs: Any,
) -> tuple[Path, dict[str, Any]]:
    # raw slightly longer than 1s window so fit path is exercised
    _write_pcm_wav(Path(out_path), duration_ms=1200, sample_rate=sample_rate)
    return Path(out_path), {"status": 200, "bytes": Path(out_path).stat().st_size}


def test_run_build_mocked_tts_writes_artifacts(tmp_path: Path) -> None:
    srt = tmp_path / "sample.srt"
    _minimal_srt(srt)
    out_dir = tmp_path / "out" / "ja"
    work_dir = tmp_path / "work"
    cfg = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=out_dir,
        work_dir=work_dir,
        voice_id="leo",
        keep_raw=True,
        also_mp3=False,
        limit=2,
    )
    cfg.validate()

    with (
        patch("srtspeak.core.pipeline.synthesize_to_file", side_effect=_fake_synthesize),
        patch("srtspeak.core.ja_yomi._call_chat_json", return_value={"cues": [{"index": 2, "text": "世界"}]}),
    ):
        report = run_build(cfg, api_key="test-key-not-real")

    assert report["status"] == "ok"
    assert report["lang"] == "ja"
    assert report["language_code"] == "ja"
    assert report["ja_yomi"] is True
    assert report["provider"] == "xai_grok"
    assert report["voice_id"] == "leo"
    assert report["cue_count"] == 2
    assert report["processed_count"] == 2
    assert "api_key" not in report
    assert "XAI_API_KEY" not in str(report)

    track = out_dir / track_filename("ja")
    assert track.is_file()
    assert report.get("track_path") == str(track) or report.get("track") == str(track)
    # last_end 2000ms ±50ms
    dur = wav_duration_ms(track, sample_rate=24000)
    assert abs(dur - 2000.0) <= 50.0

    report_path = out_dir / "report.json"
    assert report_path.is_file()

    assert len(report["cues"]) == 2
    for cue in report["cues"]:
        assert cue["cache_hit"] is False
        assert cue["raw_duration_ms"] is not None
        assert cue["fitted_duration_ms"] is not None
        assert cue["window_ms"] == 1000
        assert abs(cue["fitted_duration_ms"] - 1000) <= 15 or cue.get("hard_trim") or cue.get(
            "hard_pad"
        )

    # raw + fitted + cues present
    assert (work_dir / "ja" / "raw" / "0001.wav").is_file()
    assert (out_dir / "fitted" / "0001.wav").is_file() or (
        out_dir / "cues" / "0001.wav"
    ).is_file()


def test_run_build_cache_hit_on_second_run(tmp_path: Path) -> None:
    srt = tmp_path / "sample.srt"
    _minimal_srt(srt)
    out_dir = tmp_path / "out" / "ja"
    work_dir = tmp_path / "work"
    cfg = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=out_dir,
        work_dir=work_dir,
        voice_id="leo",
        limit=2,
    )
    calls: list[str] = []

    def _counting_synth(**kwargs: Any) -> tuple[Path, dict[str, Any]]:
        calls.append(kwargs["text"])
        return _fake_synthesize(**kwargs)

    with (
        patch("srtspeak.core.pipeline.synthesize_to_file", side_effect=_counting_synth),
        patch("srtspeak.core.ja_yomi._call_chat_json", return_value={"cues": [{"index": 2, "text": "世界"}]}),
    ):
        r1 = run_build(cfg, api_key="k")
        r2 = run_build(cfg, api_key="k")

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert len(calls) == 2  # only first run hits API
    assert all(c["cache_hit"] is True for c in r2["cues"])


def test_run_build_no_cache_bypasses_tts_cache(tmp_path: Path) -> None:
    srt = tmp_path / "sample.srt"
    _minimal_srt(srt)
    out_dir = tmp_path / "out" / "ja"
    work_dir = tmp_path / "work"
    cfg1 = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=out_dir,
        work_dir=work_dir,
        voice_id="leo",
        limit=2,
    )
    cfg_nc = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=out_dir,
        work_dir=work_dir,
        voice_id="leo",
        limit=2,
        no_cache=True,
    )
    calls: list[str] = []

    def _counting_synth(**kwargs: Any) -> tuple[Path, dict[str, Any]]:
        calls.append(kwargs["text"])
        return _fake_synthesize(**kwargs)

    with (
        patch("srtspeak.core.pipeline.synthesize_to_file", side_effect=_counting_synth),
        patch(
            "srtspeak.core.ja_yomi._call_chat_json",
            return_value={"cues": [{"index": 2, "text": "世界"}]},
        ),
    ):
        r1 = run_build(cfg1, api_key="k")
        r2 = run_build(cfg_nc, api_key="k")

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert len(calls) == 4  # second run re-hits API despite cache
    assert all(c["cache_hit"] is False for c in r2["cues"])


def test_build_service_cancel_mid_tts(tmp_path: Path) -> None:
    srt = tmp_path / "sample.srt"
    _minimal_srt(srt)
    out_dir = tmp_path / "out" / "ja"
    cfg = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=out_dir,
        work_dir=tmp_path / "work",
        voice_id="leo",
        limit=2,
    )
    token = CancellationToken()
    n = {"i": 0}

    def _cancel_after_first(**kwargs: Any) -> tuple[Path, dict[str, Any]]:
        n["i"] += 1
        if n["i"] >= 1:
            token.cancel()
        return _fake_synthesize(**kwargs)

    svc = BuildService(cfg, api_key="k", cancel_token=token)
    with (
        patch("srtspeak.core.pipeline.synthesize_to_file", side_effect=_cancel_after_first),
        patch("srtspeak.core.ja_yomi._call_chat_json", return_value={"cues": [{"index": 2, "text": "世界"}]}),
    ):
        try:
            report = svc.run()
        except BuildCancelled:
            # pipeline may raise or return cancelled report
            report_path = out_dir / "report.json"
            if report_path.is_file():
                import json

                report = json.loads(report_path.read_text(encoding="utf-8"))
            else:
                pytest.skip("cancel raised without partial report")
                return

    assert report["status"] == "cancelled"
    assert report.get("processed_count", 0) <= 2


def test_build_service_dry_run_no_tts(tmp_path: Path) -> None:
    srt = tmp_path / "sample.srt"
    _minimal_srt(srt)
    cfg = BuildConfig(
        srt_path=srt,
        lang="ja",
        language_code="ja",
        out_dir=tmp_path / "out",
        dry_run=True,
        limit=2,
    )
    with patch("srtspeak.core.pipeline.synthesize_to_file") as synth:
        report = BuildService(cfg, api_key=None).run()
        synth.assert_not_called()
    assert report["status"] == "dry_run"
    assert report["processed_count"] == 2
    assert report["estimated_cost_usd"] > 0
