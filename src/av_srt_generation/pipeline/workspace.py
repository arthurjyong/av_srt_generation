from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any, Tuple

from av_srt_generation.io.json_io import read_json, write_json


@dataclass
class WorkspaceContext:
    input_path: Path
    work_dir: Path
    media_json_path: Path
    run_log_path: Path
    media_metadata: dict[str, Any]


def _fingerprint_for_path(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"size_bytes": stat.st_size, "mtime": stat.st_mtime}


def _candidate_work_dir(base_dir: Path, suffix: int | None) -> Path:
    if suffix is None:
        return base_dir
    return base_dir.parent / f"{base_dir.name}.{suffix:03d}"


def _fingerprint_matches(existing: dict[str, Any], fingerprint: dict[str, Any], input_path: Path) -> bool:
    existing_fingerprint = existing.get("fingerprint", {})
    size = existing_fingerprint.get("size_bytes")
    mtime = existing_fingerprint.get("mtime")
    return (
        existing.get("input_path") == str(input_path)
        and size == fingerprint.get("size_bytes")
        and mtime == fingerprint.get("mtime")
    )


def _select_work_dir(base_dir: Path, fingerprint: dict[str, Any], input_path: Path) -> Tuple[Path, bool]:
    for idx in count(0):
        suffix = None if idx == 0 else idx
        candidate = _candidate_work_dir(base_dir, suffix)
        media_json = candidate / "media.json"
        if candidate.exists():
            if media_json.exists():
                try:
                    existing = read_json(media_json)
                except Exception:
                    existing = None
                if isinstance(existing, dict) and _fingerprint_matches(existing, fingerprint, input_path):
                    return candidate, False
            continue
        return candidate, True
    raise RuntimeError("Unable to select workspace directory")


def _build_media_metadata(input_path: Path, work_dir: Path, fingerprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_path": str(input_path),
        "file_name": input_path.name,
        "work_dir": str(work_dir),
        "fingerprint": fingerprint,
        "created_at": _dt.datetime.utcnow().isoformat() + "Z",
    }


def init_workspace(video_path: str | Path) -> WorkspaceContext:
    input_path = Path(video_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")

    fingerprint = _fingerprint_for_path(input_path)
    base_work_dir = input_path.parent / f"{input_path.stem}.av_srt"

    work_dir, _ = _select_work_dir(base_work_dir, fingerprint, input_path)
    work_dir.mkdir(parents=True, exist_ok=True)

    media_metadata = _build_media_metadata(input_path, work_dir, fingerprint)
    media_json_path = work_dir / "media.json"
    write_json(media_json_path, media_metadata)

    run_log_path = work_dir / "run.log"
    log_line = f"[{_dt.datetime.utcnow().isoformat()}Z] init_workspace({input_path})\n"
    with run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(log_line)

    return WorkspaceContext(
        input_path=input_path,
        work_dir=work_dir,
        media_json_path=media_json_path,
        run_log_path=run_log_path,
        media_metadata=media_metadata,
    )
