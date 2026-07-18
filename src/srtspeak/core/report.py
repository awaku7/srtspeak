"""Report helpers and cost estimate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COST_USD_PER_MILLION_CHARS = 15.0


def estimate_cost_usd(char_count: int) -> float:
    return (char_count / 1_000_000.0) * COST_USD_PER_MILLION_CHARS


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def track_filename(lang: str, *, mp3: bool = False) -> str:
    ext = "mp3" if mp3 else "wav"
    return f"GRAN_TENKU_{lang}.{ext}"
