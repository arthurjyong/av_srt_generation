from __future__ import annotations

import argparse


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

    print("av_srt_generation: not implemented yet.")
    print(f"video_path = {args.video_path}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
