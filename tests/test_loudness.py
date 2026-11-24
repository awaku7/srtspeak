from __future__ import annotations

import wave
from pathlib import Path

import pytest

from srtspeak.core.models import BuildConfig
from srtspeak.core.pipeline import (
    _normalize_loudness,
    measure_loudness,
    normalize_loudness_file,
)

_INPUT_STATS = '''{
  "input_i": "-24.00",
  "input_tp": "-6.00",
  "input_lra": "3.00",
  "input_thresh": "-34.00",
  "target_offset": "10.00",
  "output_i": "-14.00",
  "output_tp": "-1.50",
  "output_lra": "3.00"
}'''

_OUTPUT_STATS = '''{
  "input_i": "-24.00",
  "input_tp": "-6.00",
  "input_lra": "3.00",
  "input_thresh": "-34.00",
  "target_offset": "0.00",
  "normalization_type": "linear",
  "output_i": "-14.02",
  "output_tp": "-1.52",
  "output_lra": "3.00"
}'''


def test_target_lufs_validation(tmp_path: Path) -> None:
    base = BuildConfig(
        srt_path=tmp_path / "in.srt",
        lang="en",
        language_code="en-US",
        out_dir=tmp_path / "out",
        target_lufs=-14.0,
    )
    base.validate()

    with pytest.raises(ValueError, match="target_lufs"):
        BuildConfig(
            srt_path=tmp_path / "in.srt",
            lang="en",
            language_code="en-US",
            out_dir=tmp_path / "out",
            target_lufs=-40.0,
        ).validate()


def test_normalize_loudness_measures_then_applies_linear_gain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = tmp_path / "track.wav"
    track.write_bytes(b"original")
    calls: list[list[str]] = []
    responses = [_INPUT_STATS, _OUTPUT_STATS]

    class Result:
        returncode = 0
        stdout = ""

        def __init__(self, stderr: str):
            self.stderr = stderr

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            Path(args[-1]).write_bytes(b"normalized")
        return Result(responses.pop(0))

    monkeypatch.setattr("srtspeak.core.pipeline.subprocess.run", fake_run)
    report = _normalize_loudness(
        track,
        target_lufs=-14.0,
        ffmpeg="ffmpeg",
        sample_rate=48000,
        channels=1,
        sample_width=2,
    )

    assert len(calls) == 2
    assert "-" in calls[0]
    assert "print_format=json" in calls[0][calls[0].index("-af") + 1]
    second_filter = calls[1][calls[1].index("-af") + 1]
    assert "measured_I=-24.000000" in second_filter
    assert "measured_TP=-6.000000" in second_filter
    assert "measured_LRA=3.000000" in second_filter
    assert "measured_thresh=-34.000000" in second_filter
    assert "offset=10.000000" in second_filter
    assert "linear=true" in second_filter
    assert "pcm_s16le" in calls[1]
    assert track.read_bytes() == b"normalized"
    assert report["mode"] == "linear_two_pass"
    assert report["input_lufs"] == -24.0
    assert report["output_lufs"] == -14.02
    assert report["ffmpeg_normalization_type"] == "linear"
    assert not (tmp_path / "track.loudnorm.tmp.wav").exists()


def test_reports_ffmpeg_dynamic_fallback_when_linear_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = tmp_path / "limited.wav"
    track.write_bytes(b"original")
    calls: list[list[str]] = []
    dynamic_stats = _OUTPUT_STATS.replace('"linear"', '"dynamic"')

    class Result:
        returncode = 0
        stdout = ""

        def __init__(self, stderr: str):
            self.stderr = stderr

    responses = [_INPUT_STATS, dynamic_stats]

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            Path(args[-1]).write_bytes(b"normalized")
        return Result(responses.pop(0))

    monkeypatch.setattr("srtspeak.core.pipeline.subprocess.run", fake_run)
    report = _normalize_loudness(
        track,
        target_lufs=-14.0,
        ffmpeg="ffmpeg",
        sample_rate=48000,
        channels=1,
    )

    assert "linear=true" in calls[1][calls[1].index("-af") + 1]
    assert report["ffmpeg_normalization_type"] == "dynamic"
    assert report["mode"] == "dynamic_two_pass_fallback"


def test_normalize_loudness_falls_back_for_unmeasurable_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = tmp_path / "silence.wav"
    track.write_bytes(b"original")
    calls: list[list[str]] = []
    silence_stats = _INPUT_STATS.replace('"-24.00"', '"-inf"', 1)
    output_silence_stats = silence_stats.replace(
        '"output_i"', '"normalization_type": "dynamic",\n  "output_i"'
    )

    class Result:
        returncode = 0
        stdout = ""

        def __init__(self, stderr: str):
            self.stderr = stderr

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            Path(args[-1]).write_bytes(b"processed")
            return Result(output_silence_stats)
        return Result(silence_stats)

    monkeypatch.setattr("srtspeak.core.pipeline.subprocess.run", fake_run)
    report = _normalize_loudness(
        track,
        target_lufs=-14.0,
        ffmpeg="ffmpeg",
        sample_rate=48000,
        channels=1,
    )

    second_filter = calls[1][calls[1].index("-af") + 1]
    assert "measured_I=" not in second_filter
    assert report["mode"] == "dynamic_fallback"
    assert report["input_lufs"] is None


def _make_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48000)
        wav_file.writeframes(b"\0\0" * 480)


def test_measure_loudness_reads_stats_without_changing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    _make_test_wav(source)
    before = source.read_bytes()

    class Result:
        returncode = 0
        stderr = _INPUT_STATS
        stdout = ""

    monkeypatch.setattr("srtspeak.core.pipeline.subprocess.run", lambda *a, **k: Result())
    stats = measure_loudness(source, target_lufs=-14.0, ffmpeg="ffmpeg")

    assert stats == {
        "integrated_lufs": -24.0,
        "true_peak_dbtp": -6.0,
        "lra_lu": 3.0,
    }
    assert source.read_bytes() == before


def test_normalize_loudness_file_writes_a_separate_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    destination = tmp_path / "source_lufs_-14.wav"
    _make_test_wav(source)
    before = source.read_bytes()
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""

        def __init__(self, stderr: str):
            self.stderr = stderr

    responses = [_INPUT_STATS, _OUTPUT_STATS]

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            Path(args[-1]).write_bytes(b"normalized")
        return Result(responses.pop(0))

    monkeypatch.setattr("srtspeak.core.pipeline.subprocess.run", fake_run)
    normalize_loudness_file(
        source,
        destination,
        target_lufs=-14.0,
        ffmpeg="ffmpeg",
    )

    assert source.read_bytes() == before
    assert destination.read_bytes() == b"normalized"
    assert len(calls) == 2
