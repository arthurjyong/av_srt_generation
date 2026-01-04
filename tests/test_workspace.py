from __future__ import annotations

import json
import time
from pathlib import Path

from av_srt_generation.pipeline.workspace import WorkspaceContext, init_workspace


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_init_creates_workspace(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"abc")

    ctx = init_workspace(video)

    assert isinstance(ctx, WorkspaceContext)
    assert ctx.work_dir == tmp_path / "sample.av_srt"
    assert ctx.media_json_path.is_file()
    assert ctx.run_log_path.is_file()

    metadata = _read_json(ctx.media_json_path)
    assert metadata["input_path"] == str(video.resolve())
    assert metadata["fingerprint"]["size_bytes"] == 3

    log_text = ctx.run_log_path.read_text(encoding="utf-8")
    assert "init_workspace" in log_text


def test_reuse_existing_workspace_with_matching_metadata(tmp_path: Path) -> None:
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"12345")

    first_ctx = init_workspace(video)
    second_ctx = init_workspace(video)

    assert first_ctx.work_dir == second_ctx.work_dir
    assert (first_ctx.work_dir / "media.json").is_file()

    log_text = second_ctx.run_log_path.read_text(encoding="utf-8")
    assert log_text.count("init_workspace") == 2


def test_new_suffix_workspace_when_file_changes(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"initial")

    first_ctx = init_workspace(video)

    # Change file size and mtime
    time.sleep(0.01)
    video.write_bytes(b"changed size")
    time.sleep(0.01)
    Path(video).touch()

    second_ctx = init_workspace(video)

    assert second_ctx.work_dir != first_ctx.work_dir
    assert second_ctx.work_dir.name.endswith(".001")

    first_meta = _read_json(first_ctx.media_json_path)
    second_meta = _read_json(second_ctx.media_json_path)

    assert first_meta["fingerprint"] != second_meta["fingerprint"]
