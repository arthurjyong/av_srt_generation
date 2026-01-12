# Decisions

This file records non-trivial decisions so the pipeline stays consistent.

## Naming & outputs
- CLI name: `av_srt_generation`
- Output SRT beside video:
  - `<basename>.ja.srt`
  - `<basename>.zh-TW.srt`
- Working folder beside video: `<video_dir>/<basename>.av_srt/`
  - If the fingerprint differs, a numeric suffix is used (e.g. `Movie.av_srt.001`).

## Time & timestamps
- Internal timestamps: milliseconds (int)
- SRT timestamps: `HH:MM:SS,mmm`

## VAD
- Backend: Silero VAD (`silero-vad`, `torch`, `torchaudio`)
- Target behavior: aggressive segmentation, then merge/split at subtitle block stage

## ASR
- Backend: `mlx-whisper` (Apple Silicon)
- Model repo: `mlx-community/whisper-large-v3-mlx`
- Output format: `segments.asr.json` + `segments.asr.meta.json`

## Gating
- Stage: `segments.gated.json` + `segments.gated.meta.json`
- Goal: drop low-quality or non-Japanese segments before subtitle block building

## Translation
- Backend: Google Cloud Translation API (Basic v2)
- Env var: `GOOGLE_TRANSLATE_API_KEY`
- Output language: zh-TW
