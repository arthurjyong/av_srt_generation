from __future__ import annotations

import datetime as _dt
import wave
from pathlib import Path

from av_srt_generation.io.subprocess_run import run_command
from av_srt_generation.pipeline.workspace import WorkspaceContext


def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def _validate_wav(audio_path: Path) -> bool:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            rate = wav_file.getframerate()
            sampwidth = wav_file.getsampwidth()
            return channels == 1 and rate == 16000 and sampwidth == 2
    except Exception:
        return False


def extract_audio(ctx: WorkspaceContext) -> Path:
    """Extract mono 16kHz audio from the input media into ``audio.wav``.

    The operation is resumable: if a valid ``audio.wav`` already exists, the
    extraction is skipped.
    """

    audio_path = ctx.work_dir / "audio.wav"

    if audio_path.exists() and _validate_wav(audio_path):
        _log(ctx, f"extract_audio: skip (existing {audio_path.name})")
        return audio_path

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = [
        "ffmpeg",
        "-i",
        str(ctx.input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-y",
        str(audio_path),
    ]

    _log(ctx, f"extract_audio: running ffmpeg -> {audio_path.name}")
    try:
        run_command(ffmpeg_cmd)
    except RuntimeError as exc:
        _log(ctx, f"extract_audio: failed ({exc})")
        raise

    if not _validate_wav(audio_path):
        _log(ctx, "extract_audio: output validation failed")
        raise RuntimeError("ffmpeg did not produce a valid mono 16kHz wav file")

    _log(ctx, f"extract_audio: ok -> {audio_path.name}")
    return audio_path
