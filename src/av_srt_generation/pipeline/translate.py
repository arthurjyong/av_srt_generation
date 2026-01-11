from __future__ import annotations

import datetime as _dt
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from av_srt_generation.pipeline.workspace import WorkspaceContext


_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"


@dataclass
class SrtEntry:
    index: int
    start_ts: str
    end_ts: str
    lines: List[str]


def _log(ctx: WorkspaceContext, message: str) -> None:
    timestamp = _dt.datetime.utcnow().isoformat() + "Z"
    with ctx.run_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def parse_srt(text: str) -> List[SrtEntry]:
    lines = text.splitlines()
    entries: List[SrtEntry] = []
    idx = 0
    while idx < len(lines):
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines):
            break
        index_line = lines[idx].strip()
        try:
            index = int(index_line)
        except ValueError as exc:
            raise ValueError(f"Invalid SRT index line: {index_line}") from exc
        idx += 1
        if idx >= len(lines):
            raise ValueError("Unexpected end of SRT after index line")
        timing = lines[idx].strip()
        if "-->" not in timing:
            raise ValueError(f"Invalid SRT timing line: {timing}")
        start_ts, end_ts = [part.strip() for part in timing.split("-->", 1)]
        idx += 1
        text_lines: List[str] = []
        while idx < len(lines) and lines[idx].strip():
            text_lines.append(lines[idx])
            idx += 1
        entries.append(
            SrtEntry(index=index, start_ts=start_ts, end_ts=end_ts, lines=text_lines)
        )
    return entries


def render_srt(entries: Iterable[SrtEntry]) -> str:
    output_lines: List[str] = []
    for entry in entries:
        output_lines.append(str(entry.index))
        output_lines.append(f"{entry.start_ts} --> {entry.end_ts}")
        output_lines.extend(entry.lines)
        output_lines.append("")
    return "\n".join(output_lines).rstrip() + "\n"


def _translate_batch(batch: List[str], api_key: str) -> List[str]:
    payload = [("q", text) for text in batch]
    payload.extend(
        [
            ("source", "ja"),
            ("target", "zh-TW"),
            ("format", "text"),
        ]
    )
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"{_TRANSLATE_API_URL}?key={urllib.parse.quote(api_key)}"
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else ""
        raise RuntimeError(
            f"Google Translate API request failed ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Google Translate API connection failed: {exc}") from exc

    payload = json.loads(body)
    translations = payload.get("data", {}).get("translations", [])
    if not isinstance(translations, list) or len(translations) != len(batch):
        raise RuntimeError("Google Translate API response missing translations")
    return [html.unescape(item.get("translatedText", "")) for item in translations]


def _batch_items(items: List[str], batch_size: int) -> List[List[str]]:
    return [items[idx : idx + batch_size] for idx in range(0, len(items), batch_size)]


def translate_srt_zh_tw(
    ctx: WorkspaceContext,
    srt_path: Path,
    *,
    overwrite: bool = True,
) -> Path:
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_TRANSLATE_API_KEY is required for zh-TW translation. "
            "Set the environment variable to enable Google Translate."
        )

    output_path = ctx.input_path.parent / f"{ctx.input_path.stem}.zh-TW.srt"
    if output_path.exists() and not overwrite:
        _log(ctx, f"translate_zh_tw: skip (exists) -> {output_path.name}")
        return output_path

    entries = parse_srt(srt_path.read_text(encoding="utf-8"))
    texts = ["\n".join(entry.lines) for entry in entries]
    batches = _batch_items(texts, 100)

    _log(
        ctx,
        f"translate_zh_tw: start entries={len(entries)} batches={len(batches)}",
    )

    translated_texts: List[str] = []
    for batch in batches:
        translated_texts.extend(_translate_batch(batch, api_key))

    translated_entries: List[SrtEntry] = []
    for entry, translated in zip(entries, translated_texts, strict=True):
        translated_entries.append(
            SrtEntry(
                index=entry.index,
                start_ts=entry.start_ts,
                end_ts=entry.end_ts,
                lines=translated.split("\n"),
            )
        )

    output_path.write_text(render_srt(translated_entries), encoding="utf-8")
    _log(
        ctx,
        f"translate_zh_tw: ok -> {output_path.name} entries={len(entries)} "
        f"batches={len(batches)}",
    )
    return output_path
