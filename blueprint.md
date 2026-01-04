# Blueprint: `av_srt_generation <video_path>` → JP SRT + ZH-Hant SRT (Quality-first, Aggressive Drop, Resumable)

## 0) Goal

Given a large Japanese video file (≈1–2 hours, 5–6GB) with substantial non-speech noise, generate:

1. **Japanese subtitles** (`.srt`) with accurate timestamps and readable chunking.
2. **Traditional Chinese subtitles** (`.srt`) translated from Japanese, same timestamps.

Priorities:

* **Quality > time**
* **Aggressive filtering**: prefer dropping ambiguous/unclear speech over including noise/hallucinations
* **Resumable** at every stage

---

## 1) Command-line UX

Run:

* `av_srt_generation <video_path>`

Behavior:

* Automatically create a **work folder next to the video**, named **exactly the same as the video basename** (without extension).
* All intermediate artifacts go inside that folder.
* Final `.srt` outputs are written **beside the original video** and share the same basename, with language suffixes.

Example:

* Input: `/path/Movie01.mp4`
* Work folder: `/path/Movie01/`
* Outputs beside video:

  * `/path/Movie01.ja.srt`
  * `/path/Movie01.zh-Hant.srt`

Resume policy:

* If work folder exists and matches the same video (verified via stored metadata), resume from existing artifacts.
* If a different video is detected under the same basename folder, create a new folder variant (e.g. `Movie01__2`) or refuse unless forced (implementation decision later).

---

## 2) Subtitle filename convention (VLC-friendly)

Outputs:

* `<basename>.ja.srt`
* `<basename>.zh-Hant.srt`

Rationale:

* Players like VLC commonly auto-detect external subtitles that share the same basename and differ by suffix/extra tokens.
* Using explicit language tags is conventional and easy to manage.

(If needed later, also support `<basename>.jpn.srt` / `<basename>.zho.srt`, but default to `.ja` and `.zh-Hant`.)

---

## 3) High-level Pipeline (Stages)

1. Probe video + initialize workspace
2. Extract canonical audio WAV
3. VAD speech segmentation (aggressive)
4. ASR per speech segment (Whisper large-v3, quality-first)
5. Aggressive quality gating (drop noise/hallucination)
6. Build subtitle blocks (merge/split for readability)
7. Japanese text normalization (。、？！ etc., keep filler)
8. Write Japanese SRT beside video
9. Translate each JP block with LLM (cached)
10. Write ZH-Hant SRT beside video
11. Produce logs + report

Each stage writes persistent artifacts so reruns skip completed work.

---

## 4) Workspace folder layout

Create:

* `work_dir = <video_dir>/<basename>/`

Inside `work_dir`:

```
media.json
audio.wav
segments.vad.json
asr.jsonl
subtitle_blocks_ja.json
translate_cache.jsonl
run.log
report.json
```

Final outputs (beside original video):

* `<video_dir>/<basename>.ja.srt`
* `<video_dir>/<basename>.zh-Hant.srt`

---

## 5) Resume / caching rules (key requirement)

On every run:

* Read `work_dir/media.json` if exists.
* Verify it corresponds to the same input video:

  * compare absolute path, file size, and optionally a fast hash/fingerprint (or mtime + size).
* If matched → resume.
* If not matched → either:

  * create a new unique work_dir name, OR
  * stop with clear message (future option).

Stage-level skip rules:

* If `audio.wav` exists and passes basic property check → skip extraction.
* If `segments.vad.json` exists → skip VAD.
* For ASR:

  * read existing `asr.jsonl` to determine completed `seg_id`s → skip those segments.
* SRT building is deterministic from `asr.jsonl` → can always rebuild quickly.
* Translation:

  * use `translate_cache.jsonl` keyed by hash(JP block text) → cache hits skip LLM.

Crash safety:

* Write outputs incrementally (append-only for `asr.jsonl` and cache).
* After each segment, flush to disk.

---

## 6) Stage-by-stage details

### Stage 1 — Probe + workspace init

Purpose:

* Validate input, prepare folder structure, enable resume.

Actions:

* Derive `basename` from video filename (strip extension).
* Create `work_dir` beside video if missing.
* Probe media metadata and store to `work_dir/media.json`:

  * input path
  * file size
  * duration (ms)
  * audio stream basic info (codec, channels, sample rate if available)
  * a fingerprint strategy (size + mtime, or partial hash) for resume validation
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

* Silero VAD

Aggressive defaults:

* `vad_threshold = 0.70`
* `min_speech_duration = 0.60s`
* `min_silence_duration = 0.40s`
* `pad_start = 0.15s`, `pad_end = 0.20s`
* `max_segment_len = 20s`

Post-processing:

* merge extremely short gaps only if it doesn’t exceed `max_segment_len`
* drop too-short segments
* split long segments

Output:

* `work_dir/segments.vad.json` ordered list:

  * seg_id
  * start_ms, end_ms
  * duration_ms
  * optional VAD confidence stats

Resume:

* If file exists → skip.

---

### Stage 4 — ASR per segment (quality-first)

Purpose:

* Transcribe each candidate segment.

ASR:

* faster-whisper + Whisper `large-v3`

Decode defaults:

* `language = ja`
* `beam_size = 10`
* `patience = 2.0`
* temperature fallback schedule: `[0.0, 0.2, 0.4]`
* if temp > 0: `best_of = 5`
* `condition_on_previous_text = False`

Process:

* For each segment not yet done:

  1. Cut audio slice from `audio.wav` using start/end ms.
  2. Run ASR.
  3. Collect:

     * text
     * timestamps (segment-level is enough)
     * confidence diagnostics (if available):

       * no_speech_prob
       * avg_logprob
       * compression_ratio
  4. Append record to `work_dir/asr.jsonl` immediately.

Resume:

* On start, parse `asr.jsonl` to skip completed seg_id.

---

### Stage 5 — Aggressive quality gating (drop noise/hallucination)

Purpose:

* Keep only real conversation; drop moans/noise/junk.

Hard discard if any:

* `no_speech_prob >= 0.80`
* `avg_logprob < -0.80`
* `compression_ratio > 1.8`
* empty/whitespace output
* fails “looks like Japanese” heuristic (very low Japanese character ratio)

Optional salvage (time doesn’t matter):

* if VAD suggests strong speech but fails gates:

  * rerun at temp=0.2 (or 0.4)
  * accept only if gates pass

Persist:

* each `asr.jsonl` record includes:

  * accepted true/false
  * discard_reason if false

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

## 7) LLM Translation (JP → Traditional Chinese)

### Stage 9 — Translate per block (cached)

Purpose:

* Translate each Japanese subtitle block into Traditional Chinese while preserving timestamps.

Cache:

* `work_dir/translate_cache.jsonl` append-only
* key = hash(normalized JP text)
* value = zh-Hant translation + metadata (model name)

Translation constraints (conceptual prompt):

* Translate Japanese → Traditional Chinese (zh-Hant)
* faithful meaning, concise subtitle style
* no added content, no explanations
* keep max 2 lines, avoid overly long lines
* keep filler translated naturally (can adjust later)

Resume:

* if hash exists in cache → skip LLM call

---

### Stage 10 — Write ZH-Hant SRT beside video

Output path:

* `<video_dir>/<basename>.zh-Hant.srt`

Timestamps identical to JP SRT.
Text = translated blocks.

---

## 8) Logging + report

`work_dir/run.log`:

* stage start/end
* counts: VAD segments, ASR done/resumed, accepted vs discarded + reasons
* subtitle blocks count
* translation cache hit/miss

`work_dir/report.json`:

* summary metrics (accept rate, avg block duration, etc.)

---

## 9) Default settings summary (documented)

ASR:

* faster-whisper `large-v3`
* beam=10, patience=2.0
* temps=[0.0,0.2,0.4], best_of=5 when temp>0
* condition_on_previous_text=false

Aggressive discard:

* no_speech_prob ≥ 0.80
* avg_logprob < -0.80
* compression_ratio > 1.8
* non-Japanese junk heuristic

VAD:

* threshold=0.70
* min_speech=0.60s
* min_silence=0.40s
* pad start/end=0.15/0.20s
* max seg len=20s

Subtitles:

* merge gap ≤ 250ms
* max block duration 6.0s
* max 2 lines
* ~22 chars/line
* target ≤ 12 chars/sec

Translation:

* LLM per block
* cached by hash
* output zh-Hant

---
