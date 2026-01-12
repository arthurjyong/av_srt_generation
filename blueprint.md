# Blueprint: `av_srt_generation <video_path>` → JP SRT + zh-TW SRT (Quality-first, Aggressive Drop, Resumable)

## 0) Goal

Given a large Japanese video file (≈1–2 hours, 5–6GB) with substantial non-speech noise, generate:

1. **Japanese subtitles** (`.srt`) with accurate timestamps and readable chunking.
2. **Traditional Chinese subtitles** (`.srt`, zh-TW) translated from Japanese, same timestamps.

Priorities:

* **Quality > time**
* **Aggressive filtering**: prefer dropping ambiguous/unclear speech over including noise/hallucinations
* **Resumable** at every stage

---

## 1) Command-line UX

Run:

* `av_srt_generation <video_path>`

Behavior:

* Automatically create a **work folder next to the video**, named **`<basename>.av_srt`**.
* All intermediate artifacts go inside that folder.
* Final `.srt` outputs are written **beside the original video** and share the same basename, with language suffixes.

Example:

* Input: `/path/Movie01.mp4`
* Work folder: `/path/Movie01.av_srt/`
* Outputs beside video:

  * `/path/Movie01.ja.srt`
  * `/path/Movie01.zh-TW.srt`

Resume policy:

* If work folder exists and matches the same video (verified via stored metadata), resume from existing artifacts.
* If a different video is detected under the same basename, create a new folder variant (e.g. `Movie01.av_srt.001`).

---

## 2) Subtitle filename convention (VLC-friendly)

Outputs:

* `<basename>.ja.srt`
* `<basename>.zh-TW.srt`

Rationale:

* Players like VLC commonly auto-detect external subtitles that share the same basename and differ by suffix/extra tokens.
* Using explicit language tags is conventional and easy to manage.

(If needed later, also support `<basename>.jpn.srt` / `<basename>.zho.srt`, but default to `.ja` and `.zh-TW`.)

---

## 3) High-level Pipeline (Stages)

1. Probe video + initialize workspace
2. Extract canonical audio WAV
3. VAD speech segmentation (aggressive)
4. ASR per speech segment (mlx-whisper large-v3, quality-first)
5. Aggressive quality gating (drop noise/hallucination)
6. Build subtitle blocks (merge/split for readability)
7. Japanese text normalization (。、？！ etc., keep filler)
8. Write Japanese SRT beside video
9. Translate each JP block with Google Translate API (optional)
10. Write zh-TW SRT beside video
11. Produce logs

Each stage writes persistent artifacts so reruns skip completed work.

---

## 4) Workspace folder layout

Create:

* `work_dir = <video_dir>/<basename>.av_srt/`

Inside `work_dir`:

```
media.json
run.log
audio.wav
segments.vad.json
segments.asr.json
segments.asr.meta.json
asr_clips/
segments.gated.json
segments.gated.meta.json
subtitle_blocks_ja.json
subtitle_blocks_ja.meta.json
write_srt_ja.meta.json
```

Final outputs (beside original video):

* `<video_dir>/<basename>.ja.srt`
* `<video_dir>/<basename>.zh-TW.srt`

---

## 5) Resume / caching rules (key requirement)

On every run:

* Read `work_dir/media.json` if exists.
* Verify it corresponds to the same input video:

  * compare absolute path, file size, and mtime.
* If matched → resume.
* If not matched → create a new unique work_dir name.

Stage-level skip rules:

* If `audio.wav` exists and passes basic property check → skip extraction.
* If `segments.vad.json` exists → skip VAD.
* For ASR:

  * if `segments.asr.json` exists and `segments.asr.meta.json` matches the model + language → skip ASR.
* For gating:

  * if `segments.gated.json` + `segments.gated.meta.json` match → skip.
* SRT building is deterministic from gated segments → can always rebuild quickly.
* Translation:

  * no cache; translation runs on every `--translate-zh-tw` invocation and overwrites `.zh-TW.srt` (incurs API calls).

Crash safety:

* Write outputs per stage to deterministic filenames.

---

## 6) Stage-by-stage details

### Stage 1 — Probe + workspace init

Purpose:

* Validate input, prepare folder structure, enable resume.

Actions:

* Derive `basename` from video filename (strip extension).
* Create `work_dir` beside video if missing.
* Store metadata to `work_dir/media.json`:

  * input path
  * file name
  * work dir path
  * fingerprint (size + mtime) for resume validation
  * created timestamp
* Initialize `work_dir/run.log` header.

Failure:

* If probe fails → abort with log.

---

### Stage 2 — Extract canonical audio (`work_dir/audio.wav`)

Purpose:

* Produce stable, ASR/VAD-friendly audio.

Output format:

* mono, 16kHz, PCM WAV

Rule:

* All later cutting uses this WAV (do not re-extract from video repeatedly).

Resume:

* If exists and seems valid → skip.

---

### Stage 3 — VAD segmentation (aggressive)

Purpose:

* Identify candidate speech intervals.

VAD engine:

* Silero VAD (torch hub)

Defaults:

* Silero defaults for speech detection
* max segment length = 30s (`max_segment_ms=30000`)

Post-processing:

* normalize to non-overlapping segments
* split any segment longer than `max_segment_ms`

Output:

* `work_dir/segments.vad.json` ordered list:

  * seg_id
  * start_ms, end_ms

Resume:

* If file exists → skip.

---

### Stage 4 — ASR per segment (quality-first)

Purpose:

* Transcribe each candidate segment.

ASR:

* `mlx-whisper` with `mlx-community/whisper-large-v3-mlx`

Process:

* For each segment:

  1. Cut an audio slice from `audio.wav` using start/end ms.
  2. Run ASR for that slice with `language=ja`.
  3. Store results in `segments.asr.json` plus `segments.asr.meta.json`.

Resume:

* If `segments.asr.json` exists and the metadata matches the model + language, skip ASR.

---

### Stage 5 — Quality gating (drop noise/hallucination)

Purpose:

* Keep only real conversation; drop moans/noise/junk.

Current heuristics (see `GateConfig` in code):

* minimum text length
* maximum characters per second
* minimum Japanese character ratio
* max repeated character ratio
* drop if the segment is punctuation-only

Persist:

* results stored in `segments.gated.json` with metadata in `segments.gated.meta.json`

---

### Stage 6 — Build subtitle blocks (readability)

Purpose:

* Convert accepted ASR segments into SRT-ready blocks.

Merge rule:

* merge adjacent accepted segments if:

  * gap ≤ 250ms
  * and merged duration ≤ 6.0s
  * and readable under constraints

Split rules:

* If duration > 6.0s or text too long:

  * split by punctuation first
  * else split mid-text sensibly
  * timestamps based on segment boundaries when possible

Readability constraints:

* max duration 6.0s per block
* min duration ~0.8s
* max 2 lines
* ~22 Japanese chars per line
* target ≤ 12 Japanese chars/sec; if exceeded → split

Output:

* `work_dir/subtitle_blocks_ja.json`:

  * block_id
  * start_ms/end_ms
  * normalized JP text

---

### Stage 7 — Japanese normalization

Apply to each block:

* `, → 、`
* `. → 。`
* `? → ？`
* `! → ！`
* clean spacing
* keep filler words

(Do after chunking so punctuation helps splitting logic.)

---

### Stage 8 — Write Japanese SRT beside video

Output path:

* `<video_dir>/<basename>.ja.srt`

SRT:

* 1-indexed
* `HH:MM:SS,mmm --> HH:MM:SS,mmm`
* 1–2 lines per block

---

## 7) Translation (JP → zh-TW)

### Stage 9 — Translate per block (optional)

Purpose:

* Translate each Japanese subtitle block into Traditional Chinese (zh-TW) while preserving timestamps.

Backend:

* Google Cloud Translation API (Basic v2) via `GOOGLE_TRANSLATE_API_KEY`

Resume:

* No cache; translation runs on every `--translate-zh-tw` invocation and overwrites `.zh-TW.srt` (incurs API calls).

---

### Stage 10 — Write zh-TW SRT beside video

Output path:

* `<video_dir>/<basename>.zh-TW.srt`

Timestamps identical to JP SRT.
Text = translated blocks.

---

## 8) Logging

`work_dir/run.log`:

* stage start/end
* counts: VAD segments, ASR done/resumed, accepted vs discarded + reasons
* subtitle blocks count
* translation requests when enabled

There is no structured `report.json` output yet.

---

## 9) Default settings summary (documented)

ASR:

* `mlx-community/whisper-large-v3-mlx`
* language = `ja`

Gating:

* see `GateConfig` (min text chars, chars/sec, JP ratio, repeated chars, punctuation-only)

VAD:

* Silero VAD defaults
* max segment length = 30s (`max_segment_ms=30000`)

Subtitles:

* merge gap ≤ 250ms
* max block duration 6.0s
* max 2 lines
* ~22 chars/line
* target ≤ 12 chars/sec

Translation:

* Google Translate API v2 per block
* no cache; reruns with `--translate-zh-tw` overwrite `.zh-TW.srt` and incur API calls
* output zh-TW

---
