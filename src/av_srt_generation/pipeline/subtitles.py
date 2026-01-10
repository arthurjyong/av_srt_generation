from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from av_srt_generation.io.json_io import read_json, write_json
from av_srt_generation.pipeline.workspace import WorkspaceContext


_SPLIT_PUNCT = "。！？、,.!?"


@dataclass
class Stage6Config:
    merge_gap_ms: int = 250
    max_block_ms: int = 6000
    min_block_ms: int = 800
    max_lines: int = 2
    chars_per_line: int = 22
    target_chars_per_sec: float = 12.0

    @property
    def max_chars_per_block(self) -> int:
        return self.max_lines * self.chars_per_line


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Block:
    start_ms: int
    end_ms: int
    text: str
    segments: List[Segment]


def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def count_jp_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def choose_split_point(text: str) -> int:
    if not text:
        return 0
    midpoint = len(text) // 2
    candidates = [idx for idx, ch in enumerate(text[:-1]) if ch in _SPLIT_PUNCT]
    if not candidates:
        return midpoint
    best_idx = min(
        candidates,
        key=lambda idx: (abs(idx - midpoint), 0 if idx <= midpoint else 1),
    )
    split_at = best_idx + 1
    if split_at <= 0 or split_at >= len(text):
        return midpoint
    return split_at


def format_timestamp(ms: int) -> str:
    if ms < 0:
        ms = 0
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def normalize_japanese_text(text: str) -> str:
    replacements = str.maketrans({",": "、", ".": "。", "?": "？", "!": "！"})
    normalized = text.translate(replacements)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([、。！？])\s*", r"\1", normalized)
    return normalized.strip()


def wrap_japanese(text: str, chars_per_line: int, max_lines: int) -> List[str]:
    lines: List[str] = []
    remaining = text
    punctuation = set(_SPLIT_PUNCT)
    while remaining:
        if len(lines) >= max_lines:
            break
        if len(remaining) <= chars_per_line:
            lines.append(remaining)
            remaining = ""
            break
        window_start = max(chars_per_line - 4, 1)
        window = remaining[:chars_per_line]
        split_idx = None
        for idx in range(chars_per_line - 1, window_start - 1, -1):
            if window[idx] in punctuation:
                split_idx = idx + 1
                break
        if split_idx is None:
            split_idx = chars_per_line
        lines.append(remaining[:split_idx])
        remaining = remaining[split_idx:]
    if remaining:
        if len(lines) < max_lines:
            lines.append(remaining)
        else:
            lines.extend(_wrap_remaining(remaining, chars_per_line))
    return lines


def _wrap_remaining(text: str, chars_per_line: int) -> List[str]:
    lines: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= chars_per_line:
            lines.append(remaining)
            break
        lines.append(remaining[:chars_per_line])
        remaining = remaining[chars_per_line:]
    return lines


def _coerce_stage6_config(config: Stage6Config | Dict[str, Any] | None) -> Stage6Config:
    if config is None:
        return Stage6Config()
    if isinstance(config, Stage6Config):
        return config
    return Stage6Config(**config)


def _stage6_config_payload(config: Stage6Config) -> Dict[str, Any]:
    payload = asdict(config)
    payload["max_chars_per_block"] = config.max_chars_per_block
    return payload


def _resolve_stage6_config(
    explicit: Stage6Config | Dict[str, Any] | None, meta_path: Path
) -> Stage6Config:
    if explicit is not None:
        return _coerce_stage6_config(explicit)
    if meta_path.exists():
        try:
            meta = read_json(meta_path)
        except Exception:
            meta = None
        if isinstance(meta, dict):
            stage6_config = meta.get("stage6_config")
            if isinstance(stage6_config, dict):
                payload = dict(stage6_config)
                payload.pop("max_chars_per_block", None)
                return _coerce_stage6_config(payload)
    return Stage6Config()


def _load_gated_segments(path: Path) -> List[Segment]:
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError("segments.gated.json must be a list")
    segments: List[Segment] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("segments.gated.json items must be objects")
        if not {"start_ms", "end_ms", "text"}.issubset(item.keys()):
            raise ValueError("segments.gated.json missing required keys")
        start_ms = item["start_ms"]
        end_ms = item["end_ms"]
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (start_ms, end_ms)
        ):
            raise ValueError("segments.gated.json timing fields must be integers")
        text = str(item.get("text", ""))
        segments.append(Segment(start_ms=start_ms, end_ms=end_ms, text=text))
    segments.sort(key=lambda seg: (seg.start_ms, seg.end_ms))
    return segments


def _input_fingerprint(segments_path: Path, meta_path: Path) -> str:
    if meta_path.exists():
        return _sha256_path(meta_path)
    return _sha256_path(segments_path)


def _block_duration(block: Block) -> int:
    return max(block.end_ms - block.start_ms, 0)


def _block_chars_per_sec(block: Block) -> float:
    duration = max(_block_duration(block) / 1000.0, 1e-6)
    return count_jp_chars(block.text) / duration


def _merge_segments(segments: Sequence[Segment], config: Stage6Config) -> List[Block]:
    blocks: List[Block] = []
    current: Block | None = None

    for seg in segments:
        if current is None:
            current = Block(seg.start_ms, seg.end_ms, seg.text, [seg])
            continue
        gap = max(seg.start_ms - current.end_ms, 0)
        merged_start = current.start_ms
        merged_end = max(current.end_ms, seg.end_ms)
        merged_text = current.text + seg.text
        merged_chars = count_jp_chars(merged_text)
        merged_duration = merged_end - merged_start
        merged_cps = merged_chars / max(merged_duration / 1000.0, 1e-6)
        if (
            gap <= config.merge_gap_ms
            and merged_duration <= config.max_block_ms
            and merged_chars <= config.max_chars_per_block
            and merged_cps <= config.target_chars_per_sec * 1.2
        ):
            current = Block(
                start_ms=merged_start,
                end_ms=merged_end,
                text=merged_text,
                segments=current.segments + [seg],
            )
        else:
            blocks.append(current)
            current = Block(seg.start_ms, seg.end_ms, seg.text, [seg])
    if current is not None:
        blocks.append(current)
    return blocks


def _block_needs_split(block: Block, config: Stage6Config) -> bool:
    duration = _block_duration(block)
    char_count = count_jp_chars(block.text)
    chars_per_sec = _block_chars_per_sec(block)
    return (
        duration > config.max_block_ms
        or char_count > config.max_chars_per_block
        or chars_per_sec > config.target_chars_per_sec
    )


def _ends_with_punct(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] in _SPLIT_PUNCT


def _split_on_segment_boundary(block: Block) -> tuple[Block, Block] | None:
    if len(block.segments) < 2:
        return None
    total_chars = sum(count_jp_chars(seg.text) for seg in block.segments)
    best_idx = None
    best_score: float | None = None
    left_chars = 0
    for idx in range(1, len(block.segments)):
        left_chars += count_jp_chars(block.segments[idx - 1].text)
        right_chars = max(total_chars - left_chars, 0)
        left_text = "".join(seg.text for seg in block.segments[:idx])
        score = abs(left_chars - right_chars)
        if _ends_with_punct(left_text):
            score -= 0.5
        if best_score is None or score < best_score:
            best_score = score
            best_idx = idx
    if best_idx is None:
        return None
    left_segments = block.segments[:best_idx]
    right_segments = block.segments[best_idx:]
    left_text = "".join(seg.text for seg in left_segments)
    right_text = "".join(seg.text for seg in right_segments)
    left_block = Block(
        start_ms=left_segments[0].start_ms,
        end_ms=left_segments[-1].end_ms,
        text=left_text,
        segments=list(left_segments),
    )
    right_block = Block(
        start_ms=right_segments[0].start_ms,
        end_ms=right_segments[-1].end_ms,
        text=right_text,
        segments=list(right_segments),
    )
    return left_block, right_block


def _split_inside_text(block: Block) -> tuple[Block, Block] | None:
    if len(block.text) <= 1:
        return None
    split_idx = choose_split_point(block.text)
    if split_idx <= 0 or split_idx >= len(block.text):
        split_idx = len(block.text) // 2
    left_text = block.text[:split_idx]
    right_text = block.text[split_idx:]
    total_chars = count_jp_chars(block.text)
    left_chars = count_jp_chars(left_text)
    if total_chars == 0:
        ratio = 0.5
    else:
        ratio = left_chars / total_chars
    duration = _block_duration(block)
    split_ms = int(block.start_ms + duration * ratio)
    split_ms = max(block.start_ms + 1, min(block.end_ms - 1, split_ms))
    if split_ms <= block.start_ms or split_ms >= block.end_ms:
        return None
    left_block = Block(
        start_ms=block.start_ms,
        end_ms=split_ms,
        text=left_text,
        segments=[Segment(block.start_ms, split_ms, left_text)],
    )
    right_block = Block(
        start_ms=split_ms,
        end_ms=block.end_ms,
        text=right_text,
        segments=[Segment(split_ms, block.end_ms, right_text)],
    )
    return left_block, right_block


def _split_block(block: Block) -> tuple[Block, Block] | None:
    boundary_split = _split_on_segment_boundary(block)
    if boundary_split is not None:
        return boundary_split
    return _split_inside_text(block)


def _enforce_block_constraints(block: Block, config: Stage6Config) -> List[Block]:
    if not _block_needs_split(block, config):
        return [block]
    split_pair = _split_block(block)
    if split_pair is None:
        return [block]
    left_block, right_block = split_pair
    return _enforce_block_constraints(left_block, config) + _enforce_block_constraints(
        right_block, config
    )


def build_subtitle_blocks_ja(
    ctx: WorkspaceContext,
    *,
    config: Stage6Config | Dict[str, Any] | None = None,
) -> Path:
    stage6_config = _coerce_stage6_config(config)
    segments_path = ctx.work_dir / "segments.gated.json"
    segments_meta_path = ctx.work_dir / "segments.gated.meta.json"
    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"

    if not segments_path.exists():
        _log(ctx, "stage6: missing segments.gated.json")
        raise FileNotFoundError(f"segments.gated.json not found in {ctx.work_dir}")

    input_fingerprint = _input_fingerprint(segments_path, segments_meta_path)
    if blocks_path.exists() and meta_path.exists():
        try:
            cached_meta = read_json(meta_path)
        except Exception:
            cached_meta = None
        if (
            isinstance(cached_meta, dict)
            and cached_meta.get("stage") == "stage6"
            and cached_meta.get("version") == 1
            and cached_meta.get("input_fingerprint") == input_fingerprint
            and cached_meta.get("stage6_config") == _stage6_config_payload(stage6_config)
            and cached_meta.get("blocks_sha256") == _sha256_path(blocks_path)
        ):
            _log(ctx, "stage6: skip (cache hit)")
            return blocks_path

    _log(ctx, "stage6: start")

    segments = _load_gated_segments(segments_path)
    merged = _merge_segments(segments, stage6_config)
    final_blocks: List[Block] = []
    for block in merged:
        final_blocks.extend(_enforce_block_constraints(block, stage6_config))

    final_blocks.sort(key=lambda item: (item.start_ms, item.end_ms))
    payload = [
        {
            "block_id": idx + 1,
            "start_ms": block.start_ms,
            "end_ms": block.end_ms,
            "text": block.text,
        }
        for idx, block in enumerate(final_blocks)
    ]
    write_json(blocks_path, payload)
    blocks_sha256 = _sha256_path(blocks_path)
    meta = {
        "stage": "stage6",
        "version": 1,
        "input_fingerprint": input_fingerprint,
        "stage6_config": _stage6_config_payload(stage6_config),
        "blocks_sha256": blocks_sha256,
    }
    write_json(meta_path, meta)
    _log(ctx, f"stage6: ok -> {blocks_path.name}")
    return blocks_path


def normalize_subtitle_blocks_ja(ctx: WorkspaceContext) -> Path:
    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"

    if not blocks_path.exists():
        _log(ctx, "stage7: missing subtitle_blocks_ja.json")
        raise FileNotFoundError(f"subtitle_blocks_ja.json not found in {ctx.work_dir}")

    if meta_path.exists():
        try:
            cached_meta = read_json(meta_path)
        except Exception:
            cached_meta = None
        if (
            isinstance(cached_meta, dict)
            and cached_meta.get("normalized") is True
            and cached_meta.get("normalization_version") == 1
            and cached_meta.get("normalized_blocks_sha256") == _sha256_path(blocks_path)
        ):
            _log(ctx, "stage7: skip (cache hit)")
            return blocks_path

    _log(ctx, "stage7: start")
    data = read_json(blocks_path)
    if not isinstance(data, list):
        raise ValueError("subtitle_blocks_ja.json must be a list")
    normalized: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("subtitle_blocks_ja.json items must be objects")
        text = str(item.get("text", ""))
        normalized.append({**item, "text": normalize_japanese_text(text)})
    write_json(blocks_path, normalized)
    normalized_sha = _sha256_path(blocks_path)
    meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            cached_meta = read_json(meta_path)
        except Exception:
            cached_meta = None
        if isinstance(cached_meta, dict):
            meta.update(cached_meta)
    meta.update(
        {
            "normalized": True,
            "normalization_version": 1,
            "normalized_blocks_sha256": normalized_sha,
        }
    )
    write_json(meta_path, meta)
    _log(ctx, f"stage7: ok -> {blocks_path.name}")
    return blocks_path


def _split_block_for_srt(block: Dict[str, Any]) -> list[Dict[str, Any]]:
    text = str(block.get("text", ""))
    if len(text) <= 1:
        return [block]
    split_idx = choose_split_point(text)
    if split_idx <= 0 or split_idx >= len(text):
        split_idx = len(text) // 2
    left_text = text[:split_idx]
    right_text = text[split_idx:]
    start_ms = int(block["start_ms"])
    end_ms = int(block["end_ms"])
    if end_ms - start_ms <= 1:
        return [block]
    total_chars = count_jp_chars(text)
    left_chars = count_jp_chars(left_text)
    ratio = 0.5 if total_chars == 0 else left_chars / total_chars
    duration = max(end_ms - start_ms, 0)
    split_ms = int(start_ms + duration * ratio)
    split_ms = max(start_ms + 1, min(end_ms - 1, split_ms))
    if split_ms <= start_ms or split_ms >= end_ms:
        return [block]
    return [
        {"start_ms": start_ms, "end_ms": split_ms, "text": left_text},
        {"start_ms": split_ms, "end_ms": end_ms, "text": right_text},
    ]


def _force_wrapped_lines(
    text: str, chars_per_line: int, max_lines: int
) -> List[str]:
    lines = wrap_japanese(text, chars_per_line, max_lines)
    if len(lines) <= max_lines:
        return lines
    kept = lines[: max_lines - 1]
    remainder = "".join(lines[max_lines - 1 :])
    return kept + [remainder]


def _prepare_srt_blocks(
    ctx: WorkspaceContext,
    blocks: Iterable[Dict[str, Any]],
    chars_per_line: int,
    max_lines: int,
) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    queue = list(blocks)
    while queue:
        block = queue.pop(0)
        text = str(block.get("text", ""))
        lines = wrap_japanese(text, chars_per_line, max_lines)
        if len(lines) <= max_lines:
            prepared.append(
                {"start_ms": block["start_ms"], "end_ms": block["end_ms"], "text": text}
            )
            continue
        split_blocks = _split_block_for_srt(block)
        if (
            len(split_blocks) == 1
            and split_blocks[0].get("start_ms") == block.get("start_ms")
            and split_blocks[0].get("end_ms") == block.get("end_ms")
            and split_blocks[0].get("text") == block.get("text")
        ):
            block_id = block.get("block_id", "?")
            duration_ms = int(block.get("end_ms", 0)) - int(block.get("start_ms", 0))
            _log(
                ctx,
                "stage8: warn unsplittable "
                f"block_id={block_id} duration_ms={duration_ms} forcing wrap",
            )
            forced_lines = _force_wrapped_lines(text, chars_per_line, max_lines)
            prepared.append(
                {
                    "start_ms": block["start_ms"],
                    "end_ms": block["end_ms"],
                    "text": text,
                    "lines": forced_lines,
                }
            )
            continue
        block_id = block.get("block_id", "?")
        _log(ctx, f"stage8: warn split block_id={block_id}")
        queue = split_blocks + queue
    return prepared


def _render_srt(blocks: Sequence[Dict[str, Any]], chars_per_line: int, max_lines: int) -> str:
    lines: List[str] = []
    for idx, block in enumerate(blocks, start=1):
        start_ms = int(block["start_ms"])
        end_ms = int(block["end_ms"])
        text = str(block.get("text", ""))
        wrapped = block.get("lines")
        if not isinstance(wrapped, list):
            wrapped = wrap_japanese(text, chars_per_line, max_lines)
        lines.append(str(idx))
        lines.append(f"{format_timestamp(start_ms)} --> {format_timestamp(end_ms)}")
        lines.extend(wrapped)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_srt_ja(
    ctx: WorkspaceContext,
    *,
    config: Stage6Config | Dict[str, Any] | None = None,
) -> Path:
    blocks_path = ctx.work_dir / "subtitle_blocks_ja.json"
    meta_path = ctx.work_dir / "subtitle_blocks_ja.meta.json"
    srt_meta_path = ctx.work_dir / "write_srt_ja.meta.json"
    output_path = ctx.input_path.parent / f"{ctx.input_path.stem}.ja.srt"

    if not blocks_path.exists():
        _log(ctx, "stage8: missing subtitle_blocks_ja.json")
        raise FileNotFoundError(f"subtitle_blocks_ja.json not found in {ctx.work_dir}")

    normalized_sha = _sha256_path(blocks_path)
    stage6_config = _resolve_stage6_config(config, meta_path)
    stage8_config_payload = _stage6_config_payload(stage6_config)
    if srt_meta_path.exists() and output_path.exists():
        try:
            cached_meta = read_json(srt_meta_path)
        except Exception:
            cached_meta = None
        if (
            isinstance(cached_meta, dict)
            and cached_meta.get("stage") == "stage8"
            and cached_meta.get("version") == 1
            and cached_meta.get("normalized_blocks_sha256") == normalized_sha
            and cached_meta.get("wrap_config") == stage8_config_payload
            and cached_meta.get("output_path") == str(output_path)
        ):
            _log(ctx, "stage8: skip (cache hit)")
            return output_path

    _log(ctx, "stage8: start")
    data = read_json(blocks_path)
    if not isinstance(data, list):
        raise ValueError("subtitle_blocks_ja.json must be a list")
    prepared = _prepare_srt_blocks(
        ctx,
        data,
        chars_per_line=stage6_config.chars_per_line,
        max_lines=stage6_config.max_lines,
    )
    srt_text = _render_srt(
        prepared, stage6_config.chars_per_line, stage6_config.max_lines
    )
    output_path.write_text(srt_text, encoding="utf-8")
    meta = {
        "stage": "stage8",
        "version": 1,
        "normalized_blocks_sha256": normalized_sha,
        "wrap_config": stage8_config_payload,
        "output_path": str(output_path),
    }
    write_json(srt_meta_path, meta)
    _log(ctx, f"stage8: ok -> {output_path.name}")
    return output_path
