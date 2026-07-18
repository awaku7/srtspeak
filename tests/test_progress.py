"""Tests for progress weights and cancellation."""

from __future__ import annotations

import pytest

from srtspeak.core.cancel import BuildCancelled, CancellationToken
from srtspeak.core.progress import ProgressEvent, overall_percent


def test_overall_percent_weights() -> None:
    # parse/resolve 2%, tts 55%, fit 30%, timeline 10%, report 3%
    assert overall_percent(stage="parse", stage_fraction=1.0) == pytest.approx(2.0)
    assert overall_percent(stage="tts", stage_fraction=0.0) == pytest.approx(2.0)
    assert overall_percent(stage="tts", stage_fraction=1.0) == pytest.approx(57.0)
    assert overall_percent(stage="fit", stage_fraction=1.0) == pytest.approx(87.0)
    assert overall_percent(stage="timeline", stage_fraction=1.0) == pytest.approx(97.0)
    assert overall_percent(stage="report", stage_fraction=1.0) == pytest.approx(100.0)


def test_progress_event_fields() -> None:
    ev = ProgressEvent(
        percent=34.2,
        stage="tts",
        current=101,
        total=293,
        message="cue",
        cue_index=101,
        lang="ja",
    )
    assert ev.percent == 34.2
    assert ev.stage == "tts"


def test_cancel_token() -> None:
    tok = CancellationToken()
    tok.check()
    tok.cancel()
    with pytest.raises(BuildCancelled):
        tok.check()
