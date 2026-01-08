from __future__ import annotations

import json
from pathlib import Path

import pytest

from av_srt_generation.pipeline.vad import (
    _get_silero_get_speech_timestamps,
    _normalize_segments,
    _validate_cached_segments,
    vad_segment,
)
from av_srt_generation.pipeline.workspace import init_workspace


def test_normalize_segments_orders_and_splits() -> None:
    duration_ms = 70000
    raw_segments = [
        (0, 65000),  # overly long
        (65000, 70000),  # adjacent boundary
        (1000, 2000),  # out of order but within span
    ]

    normalized = _normalize_segments(raw_segments, duration_ms=duration_ms, max_length_ms=20000)

    assert all(start < end for start, end in normalized)
    assert all(0 <= start < end <= duration_ms for start, end in normalized)
    assert all(end - start <= 20000 for start, end in normalized)

    for idx in range(1, len(normalized)):
        assert normalized[idx - 1][1] <= normalized[idx][0]

    assert normalized[0][0] == 0
    assert normalized[-1][1] == duration_ms


def test_validate_cached_segments_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "segments.vad.json"
    payload = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000},
        {"seg_id": 1, "start_ms": 1000, "end_ms": 2000},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _validate_cached_segments(path)

    path.write_text(json.dumps([{"bad": True}]), encoding="utf-8")
    assert not _validate_cached_segments(path)

    corrupt_cases = [
        [
            {"seg_id": 0, "start_ms": 0, "end_ms": 1000},
            {"seg_id": 2, "start_ms": 1000, "end_ms": 2000},  # non-monotonic id
        ],
        [
            {"seg_id": 0, "start_ms": 0, "end_ms": 1000},
            {"seg_id": 1, "start_ms": 900, "end_ms": 2000},  # overlap
        ],
        [
            {"seg_id": 0, "start_ms": -1, "end_ms": 1000},  # negative
        ],
        [
            {"seg_id": 0, "start_ms": 0, "end_ms": 0},  # end <= start
        ],
        [
            {"seg_id": "0", "start_ms": "0", "end_ms": "1000"},  # wrong types
        ],
        [
            {"seg_id": 0, "start_ms": 0},  # missing key
        ],
    ]

    for corrupt in corrupt_cases:
        path.write_text(json.dumps(corrupt), encoding="utf-8")
        assert not _validate_cached_segments(path)


def test_vad_segment_uses_cache(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    cached_segments = ctx.work_dir / "segments.vad.json"
    cached_segments.write_text(
        json.dumps([{"seg_id": 0, "start_ms": 0, "end_ms": 1000}]),
        encoding="utf-8",
    )

    result_path = vad_segment(ctx)

    assert result_path == cached_segments
    assert not (ctx.work_dir / "audio.wav").exists()
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "vad: skip (cache hit)" in log_text


def test_vad_segment_requires_audio_when_no_cache(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    with pytest.raises(FileNotFoundError, match="audio.wav"):
        vad_segment(ctx)


def _write_silent_wav(path: Path, duration_ms: int = 1000, sample_rate: int = 16000) -> None:
    import wave
    import struct

    num_frames = int(sample_rate * (duration_ms / 1000))
    silence = struct.pack("<h", 0) * num_frames

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silence)


def test_vad_segment_errors_when_dependencies_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    audio_path = ctx.work_dir / "audio.wav"
    _write_silent_wav(audio_path)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError) as excinfo:
        vad_segment(ctx)

    message = str(excinfo.value)
    assert "optional dependencies" in message
    assert "pip install torch silero-vad" in message
    assert "rerun" in message


def test_get_silero_get_speech_timestamps_accepts_dict_or_tuple() -> None:
    def marker():
        return "ok"

    assert _get_silero_get_speech_timestamps({"get_speech_timestamps": marker}) is marker
    assert _get_silero_get_speech_timestamps((marker,)) is marker
    assert _get_silero_get_speech_timestamps([marker]) is marker
    assert _get_silero_get_speech_timestamps({}) is None
