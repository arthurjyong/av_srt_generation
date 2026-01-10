from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from av_srt_generation.io.json_io import read_json, write_json
from av_srt_generation.pipeline.workspace import WorkspaceContext


_JAPANESE_CHAR_RE = re.compile(
    r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]"
)


@dataclass
class GateConfig:
    min_text_chars: int = 2
    max_chars_per_sec: float = 20.0
    min_japanese_char_ratio: float = 0.30
    max_repeated_char_ratio: float = 0.60
    drop_if_contains_only_punct: bool = True


def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _load_asr_segments(path: Path) -> List[Dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError("ASR segments must be a list")

    segments: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("ASR segments must be dictionaries")
        if not {"seg_id", "start_ms", "end_ms", "text"}.issubset(item.keys()):
            raise ValueError("ASR segments missing required keys")
        seg_id = item["seg_id"]
        start_ms = item["start_ms"]
        end_ms = item["end_ms"]
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (seg_id, start_ms, end_ms)
        ):
            raise ValueError("ASR segments must have integer timing fields")
        text = _normalize_text(item.get("text", ""))
        segments.append(
            {"seg_id": seg_id, "start_ms": start_ms, "end_ms": end_ms, "text": text}
        )

    return segments


def _asr_fingerprint(segments: List[Dict[str, Any]]) -> Tuple[str, int]:
    lines = []
    for item in segments:
        seg_id = item["seg_id"]
        start_ms = item["start_ms"]
        end_ms = item["end_ms"]
        text = _normalize_text(item.get("text", ""))
        lines.append(f"{seg_id}|{start_ms}|{end_ms}|{text}")
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(segments)


def _strip_punct_and_space(text: str) -> str:
    return re.sub(r"[\W_]+", "", text)


def _japanese_char_ratio(text: str) -> float:
    jp_count = 0
    denom = 0
    for ch in text:
        if _JAPANESE_CHAR_RE.match(ch):
            jp_count += 1
            denom += 1
        elif ch.isalnum():
            denom += 1
    if denom == 0:
        return 0.0
    return jp_count / denom


def _repeated_char_ratio(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 0.0
    counts: Dict[str, int] = {}
    for ch in compact:
        counts[ch] = counts.get(ch, 0) + 1
    return max(counts.values()) / len(compact)


def _should_drop(
    text: str,
    duration_sec: float,
    language: str,
    config: GateConfig,
) -> Tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return True, "empty"

    if config.drop_if_contains_only_punct:
        if not _strip_punct_and_space(text):
            return True, "punct-only"

    if len(stripped) < config.min_text_chars and duration_sec >= 1.0:
        return True, "too-short"

    chars_per_sec = len(stripped) / duration_sec
    if chars_per_sec > config.max_chars_per_sec:
        return True, "too-fast"

    if language == "ja":
        ratio = _japanese_char_ratio(text)
        if ratio < config.min_japanese_char_ratio:
            return True, "low-ja-ratio"

    if _repeated_char_ratio(text) > config.max_repeated_char_ratio:
        return True, "repeated-char"

    return False, ""


def _meta_matches(
    meta: Any,
    language: str,
    config: GateConfig,
    asr_sha256: str,
    asr_count: int,
) -> bool:
    if not isinstance(meta, dict):
        return False
    if meta.get("stage") != "gate" or meta.get("version") != 1:
        return False
    if meta.get("language") != language:
        return False
    if meta.get("config") != asdict(config):
        return False
    input_meta = meta.get("input", {})
    if not isinstance(input_meta, dict):
        return False
    return input_meta.get("asr_sha256") == asr_sha256 and input_meta.get("asr_count") == asr_count


def gate_segments(
    ctx: WorkspaceContext,
    *,
    language: str = "ja",
    config: GateConfig | None = None,
) -> Path:
    if config is None:
        config = GateConfig()

    asr_path = ctx.work_dir / "segments.asr.json"
    gated_path = ctx.work_dir / "segments.gated.json"
    meta_path = ctx.work_dir / "segments.gated.meta.json"

    if not asr_path.exists():
        _log(ctx, "gate: missing segments.asr.json")
        raise FileNotFoundError(f"segments.asr.json not found in {ctx.work_dir}")

    segments = _load_asr_segments(asr_path)
    asr_sha256, asr_count = _asr_fingerprint(segments)

    if gated_path.exists() and meta_path.exists():
        try:
            cached_meta = read_json(meta_path)
        except Exception:
            cached_meta = None
        if _meta_matches(cached_meta, language, config, asr_sha256, asr_count):
            _log(ctx, "gate: skip (cache hit)")
            return gated_path

    _log(ctx, "gate: start")

    kept: List[Dict[str, Any]] = []
    drop_logs = 0
    total = len(segments)

    for item in segments:
        start_ms = item["start_ms"]
        end_ms = item["end_ms"]
        duration_sec = max((end_ms - start_ms) / 1000.0, 1e-6)
        text = _normalize_text(item.get("text", ""))

        drop, reason = _should_drop(text, duration_sec, language, config)
        if drop:
            if drop_logs < 10:
                _log(ctx, f"gate: drop seg_id={item['seg_id']} reason={reason}")
                drop_logs += 1
            continue
        kept.append({**item, "text": text})

    write_json(gated_path, kept)
    meta = {
        "stage": "gate",
        "version": 1,
        "language": language,
        "config": asdict(config),
        "input": {"asr_sha256": asr_sha256, "asr_count": asr_count},
    }
    write_json(meta_path, meta)

    _log(ctx, f"gate: kept {len(kept)}/{total}")
    return gated_path
