from __future__ import annotations

import json
from pathlib import Path
import hashlib

from av_srt_generation.pipeline.subtitles import (
    Block,
    Segment,
    Stage6Config,
    _merge_short_blocks,
    build_subtitle_blocks_ja,
    format_timestamp,
    normalize_japanese_text,
    normalize_subtitle_blocks_ja,
    write_srt_ja,
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


def test_stage8_respects_stage6_config(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"
    text = "あ" * 55
    blocks = [{"block_id": 1, "start_ms": 0, "end_ms": 4000, "text": text}]
    blocks_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    stage6_config = Stage6Config(chars_per_line=30, max_lines=2)
    meta = {
        "stage": "stage6",
        "version": 1,
        "input_fingerprint": "test",
        "stage6_config": {
            "merge_gap_ms": stage6_config.merge_gap_ms,
            "max_block_ms": stage6_config.max_block_ms,
            "min_block_ms": stage6_config.min_block_ms,
            "max_lines": stage6_config.max_lines,
            "chars_per_line": stage6_config.chars_per_line,
            "target_chars_per_sec": stage6_config.target_chars_per_sec,
            "max_chars_per_block": stage6_config.max_chars_per_block,
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    srt_path = write_srt_ja(ctx)
    srt_text = srt_path.read_text(encoding="utf-8")
    lines = [line for line in srt_text.splitlines() if line and "-->" not in line and not line.isdigit()]
    assert len(lines) == 2
    assert max(len(line) for line in lines) <= 30


def test_stage8_unsplittable_block_forces_wrap(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"
    text = "あ" * 100
    blocks = [{"block_id": 1, "start_ms": 0, "end_ms": 1, "text": text}]
    blocks_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    meta = {
        "stage": "stage6",
        "version": 1,
        "input_fingerprint": "test",
        "stage6_config": {
            "merge_gap_ms": 250,
            "max_block_ms": 6000,
            "min_block_ms": 800,
            "max_lines": 2,
            "chars_per_line": 10,
            "target_chars_per_sec": 12.0,
            "max_chars_per_block": 20,
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    srt_path = write_srt_ja(ctx)
    srt_text = srt_path.read_text(encoding="utf-8")
    entry_lines = [
        line
        for line in srt_text.splitlines()
        if line and "-->" not in line and not line.isdigit()
    ]
    assert len(entry_lines) == 2


def test_stage6_cache_hit_after_normalize(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    gated_path = ctx.work_dir / "segments.gated.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "テスト,"},
        {"seg_id": 1, "start_ms": 1100, "end_ms": 2200, "text": "いいい"},
    ]
    gated_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    blocks_path = build_subtitle_blocks_ja(ctx)
    first_bytes = blocks_path.read_bytes()
    normalize_subtitle_blocks_ja(ctx)
    second_bytes = blocks_path.read_bytes()
    assert first_bytes != second_bytes

    first_mtime = blocks_path.stat().st_mtime_ns
    blocks_path_again = build_subtitle_blocks_ja(ctx)
    second_mtime = blocks_path_again.stat().st_mtime_ns
    assert first_mtime == second_mtime
    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "stage6: skip (cache hit)" in log_text


def test_stage6_merges_short_block(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "ああ"},
        {"seg_id": 1, "start_ms": 1100, "end_ms": 1300, "text": "いい"},
        {"seg_id": 2, "start_ms": 1400, "end_ms": 2500, "text": "うう"},
    ]
    gated_path = ctx.work_dir / "segments.gated.json"
    gated_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    config = Stage6Config(
        merge_gap_ms=150,
        min_block_ms=800,
        max_block_ms=4000,
        max_lines=2,
        chars_per_line=10,
        target_chars_per_sec=50.0,
    )
    blocks_path = build_subtitle_blocks_ja(ctx, config=config)
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    durations = [item["end_ms"] - item["start_ms"] for item in blocks]
    assert all(duration >= 800 for duration in durations)


def test_stage6_keeps_unmergeable_short_block(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "ああ"},
        {"seg_id": 1, "start_ms": 1100, "end_ms": 1300, "text": "いい"},
        {"seg_id": 2, "start_ms": 1400, "end_ms": 2400, "text": "うう"},
    ]
    gated_path = ctx.work_dir / "segments.gated.json"
    gated_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    config = Stage6Config(
        merge_gap_ms=50,
        min_block_ms=800,
        max_block_ms=1000,
        max_lines=2,
        chars_per_line=10,
        target_chars_per_sec=50.0,
    )
    blocks_path = build_subtitle_blocks_ja(ctx, config=config)
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    durations = [item["end_ms"] - item["start_ms"] for item in blocks]
    assert any(duration < 800 for duration in durations)


def _make_block(start_ms: int, end_ms: int, text: str) -> Block:
    segment = Segment(start_ms=start_ms, end_ms=end_ms, text=text)
    return Block(start_ms=start_ms, end_ms=end_ms, text=text, segments=[segment])


def test_merge_short_blocks_respects_merge_gap(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks = [
        _make_block(0, 200, "あ"),
        _make_block(5200, 5400, "い"),
    ]
    config = Stage6Config(merge_gap_ms=250, min_block_ms=800, max_block_ms=5000)
    merged = _merge_short_blocks(ctx, blocks, config)
    assert len(merged) == 2


def test_merge_short_blocks_allows_small_gap(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks = [
        _make_block(0, 200, "あ"),
        _make_block(300, 500, "い"),
    ]
    config = Stage6Config(merge_gap_ms=250, min_block_ms=800, max_block_ms=5000)
    merged = _merge_short_blocks(ctx, blocks, config)
    assert len(merged) == 1


def test_stage8_cache_invalidates_on_stage6_meta_change(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"
    text = "あああ"
    blocks = [{"block_id": 1, "start_ms": 0, "end_ms": 2000, "text": text}]
    blocks_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    normalized_sha = hashlib.sha256(blocks_path.read_bytes()).hexdigest()
    stage6_config = Stage6Config()
    meta = {
        "stage": "stage6",
        "version": 1,
        "input_fingerprint": "A",
        "stage6_config": {
            "merge_gap_ms": stage6_config.merge_gap_ms,
            "max_block_ms": stage6_config.max_block_ms,
            "min_block_ms": stage6_config.min_block_ms,
            "max_lines": stage6_config.max_lines,
            "chars_per_line": stage6_config.chars_per_line,
            "target_chars_per_sec": stage6_config.target_chars_per_sec,
            "max_chars_per_block": stage6_config.max_chars_per_block,
        },
        "normalized": True,
        "normalization_version": 1,
        "normalized_blocks_sha256": normalized_sha,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    srt_path = write_srt_ja(ctx)
    srt_meta_path = ctx.work_dir / "write_srt_ja.meta.json"
    first_meta = json.loads(srt_meta_path.read_text(encoding="utf-8"))
    assert first_meta["stage6_input_fingerprint"] == "A"

    meta["input_fingerprint"] = "B"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    srt_path_again = write_srt_ja(ctx)
    second_meta = json.loads(srt_meta_path.read_text(encoding="utf-8"))
    assert srt_path_again == srt_path
    assert second_meta["stage6_input_fingerprint"] == "B"


def test_stage8_cache_invalidates_on_upstream_meta_change(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"
    text = "あああ"
    blocks = [{"block_id": 1, "start_ms": 0, "end_ms": 2000, "text": text}]
    blocks_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    normalized_sha = hashlib.sha256(blocks_path.read_bytes()).hexdigest()
    stage6_config = Stage6Config()
    meta = {
        "stage": "stage6",
        "version": 1,
        "input_fingerprint": "A",
        "stage6_config": {
            "merge_gap_ms": stage6_config.merge_gap_ms,
            "max_block_ms": stage6_config.max_block_ms,
            "min_block_ms": stage6_config.min_block_ms,
            "max_lines": stage6_config.max_lines,
            "chars_per_line": stage6_config.chars_per_line,
            "target_chars_per_sec": stage6_config.target_chars_per_sec,
            "max_chars_per_block": stage6_config.max_chars_per_block,
        },
        "normalized": True,
        "normalization_version": 1,
        "normalized_blocks_sha256": normalized_sha,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    write_srt_ja(ctx)
    srt_meta_path = ctx.work_dir / "write_srt_ja.meta.json"
    first_meta = json.loads(srt_meta_path.read_text(encoding="utf-8"))
    first_upstream = first_meta["upstream_meta_sha256"]

    meta["new_field"] = "x"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    write_srt_ja(ctx)
    second_meta = json.loads(srt_meta_path.read_text(encoding="utf-8"))
    assert second_meta["upstream_meta_sha256"] != first_upstream


def test_stage6_reruns_when_gated_json_changes(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"vid")
    ctx = init_workspace(video)

    gated_path = ctx.work_dir / "segments.gated.json"
    gated_meta_path = ctx.work_dir / "segments.gated.meta.json"
    segments = [
        {"seg_id": 0, "start_ms": 0, "end_ms": 1000, "text": "ああ"},
        {"seg_id": 1, "start_ms": 1100, "end_ms": 2000, "text": "いい"},
    ]
    gated_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    gated_meta_path.write_text("{\"meta\": \"stable\"}\n", encoding="utf-8")

    blocks_path = build_subtitle_blocks_ja(ctx)
    first_meta = json.loads(
        (ctx.work_dir / "subtitle_blocks_ja.meta.json").read_text(encoding="utf-8")
    )

    segments[1]["text"] = "うう"
    gated_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    build_subtitle_blocks_ja(ctx)
    second_meta = json.loads(
        (ctx.work_dir / "subtitle_blocks_ja.meta.json").read_text(encoding="utf-8")
    )

    assert first_meta["input_fingerprint"] != second_meta["input_fingerprint"]
    assert blocks_path.read_text(encoding="utf-8") != ""
