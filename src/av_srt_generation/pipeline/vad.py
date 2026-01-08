from __future__ import annotations

import datetime as _dt
import wave
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from av_srt_generation.io.json_io import read_json, write_json
from av_srt_generation.pipeline.workspace import WorkspaceContext


_MISSING_DEPENDENCY_ERROR = (
    "Silero VAD requires optional dependencies (torch + silero-vad). "
    "Install them with: pip install torch silero-vad, then rerun the command."
)

def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def _validate_cached_segments(path: Path) -> bool:
    try:
        data = read_json(path)
    except Exception:
        return False

    if not isinstance(data, list):
        return False

    prev_seg_id = -1
    prev_end = -1
    for item in data:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {"seg_id", "start_ms", "end_ms"}:
            return False
        try:
            seg_id_raw = item["seg_id"]
            start_ms_raw = item["start_ms"]
            end_ms_raw = item["end_ms"]
        except Exception:
            return False
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (seg_id_raw, start_ms_raw, end_ms_raw)
        ):
            return False
        seg_id = int(seg_id_raw)
        start_ms = int(start_ms_raw)
        end_ms = int(end_ms_raw)
        if seg_id < 0 or start_ms < 0 or end_ms <= start_ms:
            return False
        if seg_id != prev_seg_id + 1:
            return False
        prev_seg_id = seg_id
        if start_ms < prev_end:
            return False
        prev_end = end_ms
    return True


def _get_silero_get_speech_timestamps(utils: object):
    if isinstance(utils, dict):
        return utils.get("get_speech_timestamps")
    if isinstance(utils, (list, tuple)):
        return utils[0] if utils else None
    return None


def _run_silero_vad(audio_bytes: bytes, sample_rate: int, channels: int) -> List[Tuple[int, int]]:
    try:  # pragma: no cover - optional dependency
        import torch
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(_MISSING_DEPENDENCY_ERROR) from exc

    try:  # pragma: no cover - optional dependency
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            verbose=False,
            trust_repo=True,
        )
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(_MISSING_DEPENDENCY_ERROR) from exc

    get_speech_timestamps = _get_silero_get_speech_timestamps(utils)
    if get_speech_timestamps is None:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Silero VAD utilities missing get_speech_timestamps. Update silero package."
        )

    waveform = torch.frombuffer(audio_bytes, dtype=torch.int16)
    if channels > 1:
        waveform = waveform.view(-1, channels)[:, 0]
    waveform = waveform.float().div(32768.0)

    with torch.inference_mode():  # pragma: no cover - optional dependency
        timestamps = get_speech_timestamps(
            waveform, model, sampling_rate=sample_rate
        )

    segments: List[Tuple[int, int]] = []
    for ts in timestamps:
        start_ms = int(ts["start"] * 1000 / sample_rate)
        end_ms = int(ts["end"] * 1000 / sample_rate)
        segments.append((start_ms, end_ms))
    return segments


def _split_segment(segment: Tuple[int, int], max_length_ms: int) -> List[Tuple[int, int]]:
    start_ms, end_ms = segment
    segments: List[Tuple[int, int]] = []
    while end_ms - start_ms > max_length_ms:
        segments.append((start_ms, start_ms + max_length_ms))
        start_ms += max_length_ms
    if end_ms > start_ms:
        segments.append((start_ms, end_ms))
    return segments


def _normalize_segments(raw_segments: Sequence[Tuple[int, int]], duration_ms: int, max_length_ms: int) -> List[Tuple[int, int]]:
    sorted_segments = sorted(raw_segments, key=lambda seg: seg[0])
    normalized: List[Tuple[int, int]] = []
    current_end = 0

    for start_ms, end_ms in sorted_segments:
        start_ms = max(0, start_ms)
        end_ms = min(duration_ms, end_ms)
        if end_ms <= start_ms:
            continue
        start_ms = max(start_ms, current_end)
        if start_ms >= end_ms:
            continue
        for piece in _split_segment((start_ms, end_ms), max_length_ms):
            normalized.append(piece)
            current_end = piece[1]
    return normalized


def _generate_segments(audio_path: Path, max_segment_ms: int) -> List[Tuple[int, int]]:
    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())
    duration_ms = int(len(frames) / (sample_rate * 2 * channels) * 1000)

    vad_segments = _run_silero_vad(frames, sample_rate, channels)
    if not vad_segments:
        vad_segments = [(0, duration_ms)]

    return _normalize_segments(vad_segments, duration_ms, max_segment_ms)


def _write_segments(path: Path, segments: Iterable[Tuple[int, int]]) -> None:
    data = [
        {"seg_id": idx, "start_ms": start_ms, "end_ms": end_ms}
        for idx, (start_ms, end_ms) in enumerate(segments)
    ]
    write_json(path, data)


def vad_segment(ctx: WorkspaceContext, max_segment_ms: int = 30000) -> Path:
    segments_path = ctx.work_dir / "segments.vad.json"

    if segments_path.exists() and _validate_cached_segments(segments_path):
        _log(ctx, "vad: skip (cache hit)")
        return segments_path

    _log(ctx, "vad: start")

    audio_path = ctx.work_dir / "audio.wav"
    if not audio_path.exists():
        _log(ctx, "vad: missing audio.wav")
        raise FileNotFoundError(f"audio.wav not found in {ctx.work_dir}")

    segments = _generate_segments(audio_path, max_segment_ms)
    _write_segments(segments_path, segments)

    _log(ctx, f"vad: wrote {len(segments)} segments")
    return segments_path
