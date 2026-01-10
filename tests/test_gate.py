from __future__ import annotations

import json
from pathlib import Path

from av_srt_generation.pipeline.gate import GateConfig, gate_segments
from av_srt_generation.pipeline.workspace import init_workspace


def _write_asr_segments(path: Path, segments: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def test_gate_basic_gating(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    asr_path = ctx.work_dir / "segments.asr.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "   "},
        {"seg_id": 1, "start_ms": 1000, "end_ms": 2000, "text": "!!!"},
        {"seg_id": 2, "start_ms": 2000, "end_ms": 4000, "text": "aaaaaaa"},
        {"seg_id": 3, "start_ms": 4000, "end_ms": 4100, "text": "fasttext"},
        {"seg_id": 4, "start_ms": 4100, "end_ms": 6000, "text": "今日は大丈夫？"},
    ]
    _write_asr_segments(asr_path, segments)

    gated_path = gate_segments(ctx)

    gated = json.loads(gated_path.read_text(encoding="utf-8"))
    assert [item["seg_id"] for item in gated] == [4]
    assert gated[0]["text"] == "今日は大丈夫？"


def test_gate_preserves_ordering(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    asr_path = ctx.work_dir / "segments.asr.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": ""},
        {"seg_id": 1, "start_ms": 1000, "end_ms": 2000, "text": "keep"},
        {"seg_id": 2, "start_ms": 2000, "end_ms": 3000, "text": ""},
        {"seg_id": 3, "start_ms": 3000, "end_ms": 4000, "text": "also keep"},
    ]
    _write_asr_segments(asr_path, segments)

    config = GateConfig(min_text_chars=1, max_chars_per_sec=100.0)
    gated_path = gate_segments(ctx, language="en", config=config)

    gated = json.loads(gated_path.read_text(encoding="utf-8"))
    assert [item["seg_id"] for item in gated] == [1, 3]


def test_gate_cache_hit(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    asr_path = ctx.work_dir / "segments.asr.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 2000, "text": "hello"},
        {"seg_id": 1, "start_ms": 2000, "end_ms": 4000, "text": "world"},
    ]
    _write_asr_segments(asr_path, segments)

    config = GateConfig(min_text_chars=1, max_chars_per_sec=100.0)
    gated_path = gate_segments(ctx, language="en", config=config)
    first_mtime = gated_path.stat().st_mtime_ns

    gated_path_again = gate_segments(ctx, language="en", config=config)
    second_mtime = gated_path_again.stat().st_mtime_ns

    assert gated_path_again == gated_path
    assert first_mtime == second_mtime
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "gate: skip (cache hit)" in log_text


def test_gate_cache_miss_on_input_change(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    asr_path = ctx.work_dir / "segments.asr.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 2000, "text": "hello"},
        {"seg_id": 1, "start_ms": 2000, "end_ms": 4000, "text": "world"},
    ]
    _write_asr_segments(asr_path, segments)

    config = GateConfig(min_text_chars=1, max_chars_per_sec=100.0)
    gated_path = gate_segments(ctx, language="en", config=config)
    first_text = gated_path.read_text(encoding="utf-8")

    segments[1]["text"] = ""
    _write_asr_segments(asr_path, segments)

    gated_path_again = gate_segments(ctx, language="en", config=config)
    second_text = gated_path_again.read_text(encoding="utf-8")

    assert first_text != second_text
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "gate: skip (cache hit)" not in log_text
