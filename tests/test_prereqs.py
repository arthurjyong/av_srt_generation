from __future__ import annotations

import shutil

import pytest

from av_srt_generation.utils.prereqs import FFMPEG_MISSING_MESSAGE, require_ffmpeg


def test_require_ffmpeg_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="ffmpeg is required") as excinfo:
        require_ffmpeg()

    assert FFMPEG_MISSING_MESSAGE in str(excinfo.value)


def test_require_ffmpeg_allows_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")

    require_ffmpeg()
