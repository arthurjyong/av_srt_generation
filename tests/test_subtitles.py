from __future__ import annotations

import json
from pathlib import Path

from av_srt_generation.pipeline.subtitles import (
    Stage6Config,
    build_subtitle_blocks_ja,
    format_timestamp,
    normalize_japanese_text,
    wrap_japanese,
)
from av_srt_generation.pipeline.workspace import init_workspace


def _write_gated_segments(path: Path, segments: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def test_format_timestamp() -> None:
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(3723004) == "01:02:03,004"


def test_normalize_japanese_text() -> None:
    text = "テスト , です!  はい ? ."
    assert normalize_japanese_text(text) == "テスト、です！はい？。"


def test_wrap_japanese_prefers_punctuation() -> None:
    text = "今日は良い天気ですね。明日も晴れるかな。"
    lines = wrap_japanese(text, chars_per_line=12, max_lines=2)
    assert len(lines) == 2
    assert lines[0].endswith("。")


def test_build_subtitle_blocks_merge_and_split(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 500, "text": "ああああ"},
        {"seg_id": 1, "start_ms": 600, "end_ms": 1100, "text": "いいい"},
        {"seg_id": 2, "start_ms": 3000, "end_ms": 9000, "text": "かかかかか。きききききき"},
    ]
    gated_path = ctx.work_dir / "segments.gated.json"
    _write_gated_segments(gated_path, segments)

    config = Stage6Config(
        merge_gap_ms=150,
        max_block_ms=6000,
        max_lines=2,
        chars_per_line=5,
        target_chars_per_sec=10.0,
    )
    blocks_path = build_subtitle_blocks_ja(ctx, config=config)

    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    assert len(blocks) == 3
    assert blocks[0]["start_ms"] == 0
    assert blocks[0]["end_ms"] == 1100
    assert blocks[1]["text"].endswith("。")
    assert blocks[1]["end_ms"] == 6000
