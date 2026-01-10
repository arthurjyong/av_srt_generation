from __future__ import annotations

import argparse

from av_srt_generation.pipeline.workspace import init_workspace
from av_srt_generation.pipeline.audio import extract_audio
from av_srt_generation.pipeline.vad import vad_segment
from av_srt_generation.pipeline.asr import asr_transcribe
from av_srt_generation.pipeline.gate import gate_segments


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="av_srt_generation",
        description="Generate Japanese + zh-Hant subtitles (.srt) from a local video (resumable pipeline).",
    )
    p.add_argument("video_path", help="Path to the input video file")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = init_workspace(args.video_path)
    audio_path = extract_audio(ctx)
    vad_path = vad_segment(ctx)
    asr_path = asr_transcribe(ctx)
    gated_path = gate_segments(ctx)

    print(f"Workspace directory: {ctx.work_dir}")
    print("Artifacts:")
    print(f"  - media metadata: {ctx.media_json_path}")
    print(f"  - run log: {ctx.run_log_path}")
    print(f"  - audio: {audio_path}")
    print(f"  - VAD segments: {vad_path}")
    print(f"  - ASR segments: {asr_path}")
    print(f"  - Gated segments: {gated_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
