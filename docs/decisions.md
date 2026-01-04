# Decisions

This file records non-trivial decisions so the pipeline stays consistent.

## Naming & outputs
- CLI name: `av_srt_generation`
- Output SRT beside video:
  - `<basename>.ja.srt`
  - `<basename>.zh-Hant.srt`
- Working folder beside video: `<video_dir>/<basename>/`

## Time & timestamps
- Internal timestamps: milliseconds (int)
- SRT timestamps: `HH:MM:SS,mmm`

## VAD
- Backend: TBD (likely Silero VAD)
- Target behavior: aggressive segmentation, then merge/split at subtitle block stage

## ASR
- Backend: TBD (Whisper / WhisperX)
- Output format: append-only `asr.jsonl` keyed by `seg_id` for resumability

## Translation
- Backend: TBD (LLM API)
- Cache key: hash(normalized Japanese subtitle text)
- Output language: zh-Hant
