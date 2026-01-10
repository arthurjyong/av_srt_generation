from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List

from av_srt_generation.io.json_io import read_json, write_json
from av_srt_generation.io.subprocess_run import run_command
from av_srt_generation.pipeline.workspace import WorkspaceContext


_MISSING_DEPENDENCY_ERROR = (
    "ASR requires optional dependency mlx-whisper (and mlx). "
    "Install: pip install mlx-whisper mlx"
)


def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def _load_vad_segments(path: Path) -> List[Dict[str, int]]:
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError("VAD segments must be a list")

    segments: List[Dict[str, int]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("VAD segments must be dictionaries")
        if not {"seg_id", "start_ms", "end_ms"}.issubset(item.keys()):
            raise ValueError("VAD segments missing required keys")
        seg_id = item["seg_id"]
        start_ms = item["start_ms"]
        end_ms = item["end_ms"]
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (seg_id, start_ms, end_ms)
        ):
            raise ValueError("VAD segments must have integer fields")
        segments.append({"seg_id": seg_id, "start_ms": start_ms, "end_ms": end_ms})

    return segments


def _asr_cache_matches(vad_segments: List[Dict[str, int]], asr_data: Any) -> bool:
    if not isinstance(asr_data, list):
        return False
    if len(asr_data) != len(vad_segments):
        return False

    for vad_seg, asr_seg in zip(vad_segments, asr_data):
        if not isinstance(asr_seg, dict):
            return False
        if not {"seg_id", "start_ms", "end_ms"}.issubset(asr_seg.keys()):
            return False
        if (
            asr_seg.get("seg_id") != vad_seg["seg_id"]
            or asr_seg.get("start_ms") != vad_seg["start_ms"]
            or asr_seg.get("end_ms") != vad_seg["end_ms"]
        ):
            return False

    return True


def _meta_matches(meta: Any, model_repo: str, language: str) -> bool:
    if not isinstance(meta, dict):
        return False
    return meta.get("model_repo") == model_repo and meta.get("language") == language


def _extract_clip(audio_path: Path, clip_path: Path, start_ms: int, end_ms: int) -> None:
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    start_sec = start_ms / 1000.0
    end_sec = end_ms / 1000.0
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(clip_path),
    ]
    run_command(ffmpeg_cmd)


def _extract_text(result: Any) -> str:
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str):
            return text.strip()
        segments = result.get("segments")
        if isinstance(segments, list):
            pieces = [
                seg.get("text", "")
                for seg in segments
                if isinstance(seg, dict)
            ]
            return " ".join(piece.strip() for piece in pieces if piece.strip())
    return ""


def _mlx_transcribe_clip(clip_path: Path, model_repo: str, language: str) -> str:
    try:  # pragma: no cover - optional dependency
        from mlx_whisper.transcribe import transcribe
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(_MISSING_DEPENDENCY_ERROR) from exc

    result = transcribe(
        str(clip_path),
        path_or_hf_repo=model_repo,
        language=language,
        task="transcribe",
        verbose=False,
        fp16=True,
    )
    return _extract_text(result)


def asr_transcribe(
    ctx: WorkspaceContext,
    model_repo: str = "mlx-community/whisper-large-v3-mlx",
    language: str = "ja",
) -> Path:
    asr_path = ctx.work_dir / "segments.asr.json"
    meta_path = ctx.work_dir / "segments.asr.meta.json"
    vad_path = ctx.work_dir / "segments.vad.json"
    vad_segments = _load_vad_segments(vad_path)

    if asr_path.exists():
        try:
            cached = read_json(asr_path)
        except Exception:
            cached = None
        try:
            cached_meta = read_json(meta_path)
        except Exception:
            cached_meta = None
        if _asr_cache_matches(vad_segments, cached) and _meta_matches(
            cached_meta, model_repo, language
        ):
            _log(ctx, "asr: skip (cache hit)")
            return asr_path

    _log(ctx, "asr: start")

    if not vad_segments:
        write_json(asr_path, [])
        write_json(meta_path, {"model_repo": model_repo, "language": language})
        _log(ctx, "asr: wrote 0 segments")
        return asr_path

    audio_path = ctx.work_dir / "audio.wav"
    if not audio_path.exists():
        _log(ctx, "asr: missing audio.wav")
        raise FileNotFoundError(f"audio.wav not found in {ctx.work_dir}")

    results: List[Dict[str, Any]] = []
    total = len(vad_segments)
    clips_dir = ctx.work_dir / "asr_clips"

    for idx, segment in enumerate(vad_segments, start=1):
        seg_id = segment["seg_id"]
        clip_path = clips_dir / f"seg_{seg_id}.wav"
        _extract_clip(audio_path, clip_path, segment["start_ms"], segment["end_ms"])
        text = _mlx_transcribe_clip(clip_path, model_repo, language)
        results.append({**segment, "text": text})
        if idx % 10 == 0:
            _log(ctx, f"asr: progress {idx}/{total}")

    write_json(asr_path, results)
    write_json(meta_path, {"model_repo": model_repo, "language": language})
    _log(ctx, f"asr: wrote {len(results)} segments")
    return asr_path
