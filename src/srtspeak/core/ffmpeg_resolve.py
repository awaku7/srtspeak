"""Resolve ffmpeg / ffprobe executables."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class FFmpegNotFoundError(RuntimeError):
    """Neither PATH nor imageio-ffmpeg provided ffmpeg."""


@dataclass(frozen=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: str | None
    source: str  # "path" | "imageio_ffmpeg"


def resolve_ffmpeg() -> FFmpegTools:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg:
        return FFmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe, source="path")
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return FFmpegTools(ffmpeg=exe, ffprobe=None, source="imageio_ffmpeg")
    except Exception:
        pass
    raise FFmpegNotFoundError(
        "ffmpeg not found on PATH and imageio-ffmpeg is unavailable"
    )


def ffmpeg_version(ffmpeg_path: str) -> str:
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        line = (proc.stdout or proc.stderr or "").splitlines()
        return line[0] if line else "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
