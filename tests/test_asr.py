from __future__ import annotations

import json
from pathlib import Path

import pytest

import av_srt_generation.pipeline.asr as asr_module
from av_srt_generation.pipeline.asr import asr_transcribe
from av_srt_generation.pipeline.workspace import init_workspace


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_asr_cache_hit_skips_transcribe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    vad_segments = [{"seg_id": 0, "start_ms": 0, "end_ms": 1000}]
    _write_json(ctx.work_dir / "segments.vad.json", vad_segments)

    cached = [{"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "hello"}]
    asr_path = ctx.work_dir / "segments.asr.json"
    _write_json(asr_path, cached)

    def fail_transcribe(*args, **kwargs) -> str:
        raise AssertionError("transcribe should not be called on cache hit")

    monkeypatch.setattr(asr_module, "_mlx_transcribe_clip", fail_transcribe)

    result = asr_transcribe(ctx)

    assert result == asr_path
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "asr: skip (cache hit)" in log_text


def test_asr_cache_miss_recomputes_and_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    (ctx.work_dir / "audio.wav").write_bytes(b"wav")
    vad_segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000},
        {"seg_id": 1, "start_ms": 1000, "end_ms": 2000},
    ]
    _write_json(ctx.work_dir / "segments.vad.json", vad_segments)
    _write_json(
        ctx.work_dir / "segments.asr.json",
        [{"seg_id": 99, "start_ms": 0, "end_ms": 1000, "text": "bad"}],
    )

    def fake_extract_clip(audio_path: Path, clip_path: Path, start_ms: int, end_ms: int) -> None:
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(b"clip")

    def fake_transcribe(clip_path: Path, model_repo: str, language: str) -> str:
        return f"text-{clip_path.stem}"

    monkeypatch.setattr(asr_module, "_extract_clip", fake_extract_clip)
    monkeypatch.setattr(asr_module, "_mlx_transcribe_clip", fake_transcribe)

    asr_path = asr_transcribe(ctx)

    data = json.loads(asr_path.read_text(encoding="utf-8"))
    assert [item["seg_id"] for item in data] == [0, 1]
    assert data[0]["text"] == "text-seg_0"
    assert data[1]["text"] == "text-seg_1"


def test_asr_output_order_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    (ctx.work_dir / "audio.wav").write_bytes(b"wav")
    vad_segments = [
        {"seg_id": 2, "start_ms": 2000, "end_ms": 3000},
        {"seg_id": 3, "start_ms": 3000, "end_ms": 4000},
    ]
    _write_json(ctx.work_dir / "segments.vad.json", vad_segments)

    def fake_extract_clip(audio_path: Path, clip_path: Path, start_ms: int, end_ms: int) -> None:
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(b"clip")

    def fake_transcribe(clip_path: Path, model_repo: str, language: str) -> str:
        seg_id = int(clip_path.stem.split("_")[-1])
        return f"seg-{seg_id}"

    monkeypatch.setattr(asr_module, "_extract_clip", fake_extract_clip)
    monkeypatch.setattr(asr_module, "_mlx_transcribe_clip", fake_transcribe)

    asr_path = asr_transcribe(ctx)

    data = json.loads(asr_path.read_text(encoding="utf-8"))
    assert [item["seg_id"] for item in data] == [2, 3]
    assert [item["start_ms"] for item in data] == [2000, 3000]
    assert [item["end_ms"] for item in data] == [3000, 4000]
    assert [item["text"] for item in data] == ["seg-2", "seg-3"]


def test_asr_empty_vad_segments(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    _write_json(ctx.work_dir / "segments.vad.json", [])

    asr_path = asr_transcribe(ctx)

    data = json.loads(asr_path.read_text(encoding="utf-8"))
    assert data == []
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "asr: wrote 0 segments" in log_text
