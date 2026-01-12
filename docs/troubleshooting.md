# Troubleshooting

## Common setup failures

### `ffmpeg` not found

Symptom:

- The CLI fails immediately with an error about `ffmpeg` missing.

Fix:

- Install ffmpeg and confirm it is on your `PATH`:
  - macOS (Homebrew): `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Check: `ffmpeg -version`

### `GOOGLE_TRANSLATE_API_KEY` missing

Symptom:

- Running with `--translate-zh-tw` fails with an error about the API key.

Fix:

```bash
export GOOGLE_TRANSLATE_API_KEY="your-api-key"
```

### `mlx-whisper` / `mlx` import error

Symptom:

- ASR fails with an import error for `mlx_whisper` or `mlx`.

Fix:

- Install the ASR dependencies explicitly:

```bash
pip install mlx-whisper mlx
```

Note: `mlx-whisper` targets Apple Silicon. On Intel/other platforms you may need a different backend (not yet exposed via CLI flags).

## Runtime hiccups

### Model downloads are slow

The first ASR run downloads `mlx-community/whisper-large-v3-mlx`. If the download is slow, retry or pre-download the model while on a stable connection.

### Permission errors when writing outputs

The working directory is created beside the input video (`<basename>.av_srt/`). Make sure the directory containing the video is writable.

## Where to look for logs

The run log is stored in the working directory as `run.log`. It includes stage start/end markers and the first few errors when they occur.
