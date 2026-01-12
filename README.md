# av_srt_generation

Resumable CLI pipeline to generate Japanese + Traditional Chinese (Taiwan) subtitles (`.srt`) from a local video.

It creates a sidecar working folder next to the video (same basename plus a `.av_srt` suffix) to store intermediate artifacts and allow safe resume/re-run. Final SRT files are written beside the original video using VLC-friendly naming (e.g. `video.ja.srt`, `video.zh-TW.srt`).

> **Apple Silicon note:** the default ASR path uses `mlx-whisper` / MLX and is intended for Apple Silicon Macs.

## Features

- One-command workflow: `av_srt_generation <video_path>`
- Creates a working folder: `<video_dir>/<video_basename>.av_srt/`
- Resumable pipeline (skips completed stages automatically)
- Voice Activity Detection (VAD) segmentation before ASR
- Subtitle chunking tuned for readability:
  - merge if gap ≤ 250 ms and max block duration ≤ 6 s
  - split long blocks sensibly (punctuation-first)
  - prefer 1–2 lines per subtitle
- Optional translation (JP → zh-TW) via Google Cloud Translation API (Basic v2)
- Writes VLC-friendly outputs:
  - `<video_basename>.ja.srt`
  - `<video_basename>.zh-TW.srt`

## Quick start (macOS, Apple Silicon)

> This repo is under active development. Expect breaking changes.

```bash
# prerequisites
brew install ffmpeg
python -m venv .venv
source .venv/bin/activate

# install (editable) with VAD + ASR extras
pip install -U pip
pip install -e ".[all]"

# run
av_srt_generation "/path/to/video.mp4"

# (optional) translate to zh-TW
export GOOGLE_TRANSLATE_API_KEY="your-api-key"
av_srt_generation --translate-zh-tw "/path/to/video.mp4"
```

First run notes:

- The ASR model (`mlx-community/whisper-large-v3-mlx`) is downloaded on first use.
- Outputs are written beside the input video; the working folder lives next to it.

## Prerequisites

- **Python:** 3.10+ (see `requires-python` in `pyproject.toml`)
- **ffmpeg:** required and must be on `PATH`
  - macOS/Homebrew: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`

Optional components (install via extras):

- **VAD** (`.[vad]`): `torch`, `torchaudio`, `onnxruntime`, `soundfile`, `silero-vad`
- **ASR** (`.[asr]`): `mlx-whisper` (plus `mlx` runtime)

> **Apple Silicon**: `mlx-whisper` targets Apple Silicon. On Intel/other platforms you may need to swap in another ASR backend (not yet exposed by flags).

## Installation

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[vad]"
pip install -e ".[asr]"
pip install -e ".[all]"  # or ".[vad,asr]"
```

## Usage

```bash
av_srt_generation "/path/to/video.mp4"
```

Enable zh-TW translation (disabled by default):

```bash
export GOOGLE_TRANSLATE_API_KEY="your-api-key"
av_srt_generation --translate-zh-tw "/path/to/video.mp4"
```

### Resume behavior

- If a matching working folder exists (same input path + file size + mtime), the pipeline resumes and skips completed stages.
- If the basename matches but the fingerprint differs, a new folder is created with a numeric suffix (e.g. `MyVideo.av_srt.001`).

### Outputs

Given:

- Input video: `/path/to/MyVideo.mp4`

This tool will create:

- Working folder: `/path/to/MyVideo.av_srt/`
- Final subtitles (beside the video):
  - `/path/to/MyVideo.ja.srt`
  - `/path/to/MyVideo.zh-TW.srt` (if translation enabled; overwritten on each run)

### Working folder structure (typical)

Inside `/path/to/MyVideo.av_srt/`:

- `media.json` — input metadata (path, size, mtime)
- `run.log` — stage-by-stage logs
- `audio.wav` — extracted canonical audio (mono 16kHz)
- `asr_clips/` — per-segment audio clips used for ASR
- `segments.vad.json` — VAD segments (ms timestamps)
- `segments.asr.json` — ASR results per segment
- `segments.asr.meta.json` — ASR model/language metadata
- `segments.gated.json` — post-gating segments
- `segments.gated.meta.json` — gating metadata
- `subtitle_blocks_ja.json` — merged/split blocks before SRT write
- `subtitle_blocks_ja.meta.json` — subtitle block metadata
- `write_srt_ja.meta.json` — SRT rendering metadata

## Configuration

Defaults are currently defined in code. The only CLI flag today is `--translate-zh-tw` (on/off).

## Google Translate setup

Translation to zh-TW is disabled by default. To enable it, set the environment
variable `GOOGLE_TRANSLATE_API_KEY` and pass `--translate-zh-tw`.

```bash
export GOOGLE_TRANSLATE_API_KEY="your-api-key"
```

Quick API test:

```bash
curl -s \
  -X POST \
  -d "q=こんにちは" \
  -d "source=ja" \
  -d "target=zh-TW" \
  -d "format=text" \
  "https://translation.googleapis.com/language/translate/v2?key=${GOOGLE_TRANSLATE_API_KEY}"
```

## Troubleshooting

- **ffmpeg not found**: install it and ensure it is on `PATH` (`brew install ffmpeg`).
- **GOOGLE_TRANSLATE_API_KEY missing**: export the key before running with `--translate-zh-tw`.
- **ASR import error (`mlx-whisper` / `mlx`)**: install `pip install mlx-whisper mlx` or use Apple Silicon.
- **Model download slow**: the first ASR run downloads the Whisper model; retry later or pre-download.
- **Permission errors**: make sure the video directory is writable (the `.av_srt` folder is created beside it).

See [docs/decisions.md](docs/decisions.md) for naming conventions and [docs/troubleshooting.md](docs/troubleshooting.md) for more detail.

## Development notes

- The pipeline is designed to be **idempotent** and **crash-safe**:
  - intermediate outputs are written deterministically
  - per-stage outputs are cached so interrupted runs can resume

## Pipeline stages (current)

* Workspace init + media fingerprinting
* Audio extraction (ffmpeg) with validation + resume
* VAD segmentation + segment splitting
* ASR (mlx-whisper) + quality gating
* Subtitle chunk builder + normalization
* SRT writer (`.ja.srt`)
* Optional translation (`.zh-TW.srt`)

## License

See `LICENSE`.
