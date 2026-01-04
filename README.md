# av_srt_generation

Resumable CLI pipeline to generate Japanese + Traditional Chinese subtitles (`.srt`) from a local video.

It creates a sidecar working folder next to the video (same basename) to store intermediate artifacts and allow safe resume/re-run. Final SRT files are written beside the original video using VLC-friendly naming (e.g. `video.ja.srt`, `video.zh-Hant.srt`).

## Features

- One-command workflow: `av_srt_generation <video_path>`
- Creates a working folder: `<video_dir>/<video_basename>/`
- Resumable pipeline (skips completed stages automatically)
- Voice Activity Detection (VAD) segmentation before ASR
- Subtitle chunking tuned for readability:
  - merge if gap ≤ 250 ms and max block duration ≤ 6 s
  - split long blocks sensibly (punctuation-first)
  - prefer 1–2 lines per subtitle
- Optional translation (JP → zh-Hant) with hashing + cache to avoid repeat LLM calls
- Writes VLC-friendly outputs:
  - `<video_basename>.ja.srt`
  - `<video_basename>.zh-Hant.srt`

## Quick start (dev)

> This repo is under active development. Expect breaking changes.

```bash
# create + activate venv (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows PowerShell

# install (editable)
pip install -U pip
pip install -e .
```

## Usage

```bash
av_srt_generation "/path/to/video.mp4"
```

### Outputs

Given:

* Input video: `/path/to/MyVideo.mp4`

This tool will create:

* Working folder: `/path/to/MyVideo/`
* Final subtitles (beside the video):

  * `/path/to/MyVideo.ja.srt`
  * `/path/to/MyVideo.zh-Hant.srt` (if translation enabled)

### Working folder structure (typical)

Inside `/path/to/MyVideo/`:

* `media.json` — input metadata (size, mtime, duration, etc.)
* `audio.wav` — extracted canonical audio (mono 16k)
* `segments.vad.json` — VAD segments (ms timestamps)
* `asr.jsonl` — per-segment ASR results (append-only; resumable)
* `subtitle_blocks_ja.json` — merged/split blocks before SRT write
* `translate_cache.jsonl` — cached translations by hash
* `report.json` — run metrics + counts
* `run.log` — stage-by-stage logs

## Configuration

Defaults are currently defined in code. Planned:

* CLI flags (e.g. `--lang`, `--no-translate`, `--resume/--force`)
* Config file support (YAML/JSON)

## Requirements

Planned / typical dependencies:

* Python 3.10+
* `ffmpeg` available on PATH
* ASR backend (e.g. Whisper/WhisperX or equivalent)
* VAD backend (e.g. Silero VAD)
* Optional translation backend (LLM API), with caching enabled by default

## Development notes

* The pipeline is designed to be **idempotent** and **crash-safe**:

  * intermediate outputs are written deterministically
  * per-segment results are appended and flushed so interrupted runs can resume

## Roadmap

* [ ] Implement workspace init + media probing
* [ ] Audio extraction (ffmpeg) with validation + resume
* [ ] VAD segmentation + segment splitting
* [ ] ASR with quality gating + salvage retry
* [ ] Subtitle chunk builder + normalization
* [ ] SRT writer (`.ja.srt`)
* [ ] Translation + cache (`.zh-Hant.srt`)
* [ ] CLI flags + config file

## License

See `LICENSE`.
