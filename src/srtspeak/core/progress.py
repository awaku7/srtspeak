"""Progress events and overall percent calculation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


STAGE_WEIGHTS: dict[str, float] = {
    "parse": 2.0,
    "tts": 55.0,
    "fit": 30.0,
    "timeline": 10.0,
    "report": 3.0,
}

_STAGE_ORDER = ("parse", "tts", "fit", "timeline", "report")


@dataclass(frozen=True)
class ProgressEvent:
    percent: float
    stage: str
    current: int
    total: int
    message: str = ""
    cue_index: int | None = None
    lang: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def overall_percent(*, stage: str, stage_fraction: float) -> float:
    """Return overall 0–100 percent given stage completion fraction [0,1]."""
    if stage not in STAGE_WEIGHTS:
        raise ValueError(f"unknown stage: {stage}")
    frac = max(0.0, min(1.0, stage_fraction))
    done = 0.0
    for name in _STAGE_ORDER:
        w = STAGE_WEIGHTS[name]
        if name == stage:
            done += w * frac
            break
        done += w
    return round(done, 4)


def dry_run_percent(*, stage_fraction: float) -> float:
    """Dry-run only uses parse/resolve/estimate; map to 0–100."""
    return round(max(0.0, min(1.0, stage_fraction)) * 100.0, 4)


def emit(
    cb: ProgressCallback | None,
    *,
    stage: str,
    stage_fraction: float,
    current: int = 0,
    total: int = 0,
    message: str = "",
    cue_index: int | None = None,
    lang: str | None = None,
) -> None:
    if cb is None:
        return
    cb(
        ProgressEvent(
            percent=overall_percent(stage=stage, stage_fraction=stage_fraction),
            stage=stage,
            current=current,
            total=total,
            message=message,
            cue_index=cue_index,
            lang=lang,
        )
    )
