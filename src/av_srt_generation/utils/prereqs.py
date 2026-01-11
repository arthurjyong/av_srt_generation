from __future__ import annotations

import shutil


FFMPEG_MISSING_MESSAGE = (
    "ffmpeg is required to run this pipeline. "
    "Install it with `brew install ffmpeg` and ensure it is on your PATH."
)


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(FFMPEG_MISSING_MESSAGE)
