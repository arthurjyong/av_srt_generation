from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest

from av_srt_generation.pipeline.audio import extract_audio
from av_srt_generation.pipeline.workspace import init_workspace


ffmpeg_missing = shutil.which("ffmpeg") is None


pytestmark = pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg is required for audio extraction tests")


def _make_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)


def _make_test_video(tmp_path: Path) -> Path:
    audio_path = tmp_path / "tone.wav"
    _make_silent_wav(audio_path)
    video_path = tmp_path / "sample.mp4"

    cmd = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=16x16:d=1",
        "-i",
        str(audio_path),
        "-shortest",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(video_path),
    ]

    from av_srt_generation.io.subprocess_run import run_command

    run_command(cmd)
    return video_path


def test_extract_audio_creates_mono_16k(tmp_path: Path) -> None:
    video_path = _make_test_video(tmp_path)

    ctx = init_workspace(video_path)
    audio_path = extract_audio(ctx)

    assert audio_path.exists()
    with wave.open(str(audio_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2

    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "extract_audio" in log_text
    assert "ok" in log_text


def test_extract_audio_skips_when_already_present(tmp_path: Path) -> None:
    video_path = _make_test_video(tmp_path)

    first_ctx = init_workspace(video_path)
    audio_path = extract_audio(first_ctx)
    first_mtime = audio_path.stat().st_mtime

    second_ctx = init_workspace(video_path)
    second_audio = extract_audio(second_ctx)

    assert second_audio == audio_path
    assert audio_path.stat().st_mtime == first_mtime

    log_text = second_ctx.run_log_path.read_text(encoding="utf-8")
    assert "extract_audio: skip" in log_text
