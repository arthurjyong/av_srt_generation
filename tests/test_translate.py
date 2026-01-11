from __future__ import annotations

from av_srt_generation.pipeline.translate import parse_srt, render_srt, SrtEntry


def test_parse_srt_round_trip() -> None:
    srt_text = (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "こんにちは\n"
        "世界\n\n"
        "2\n"
        "00:00:02,000 --> 00:00:03,000\n"
        "テスト\n"
    )
    entries = parse_srt(srt_text)
    assert len(entries) == 2
    assert entries[0].index == 1
    assert entries[0].lines == ["こんにちは", "世界"]
    assert entries[1].lines == ["テスト"]

    rendered = render_srt(entries)
    assert rendered.endswith("\n")
    assert parse_srt(rendered) == entries


def test_render_srt_preserves_lines() -> None:
    entries = [
        SrtEntry(
            index=1,
            start_ts="00:00:00,000",
            end_ts="00:00:01,500",
            lines=["一行目", "二行目"],
        )
    ]
    rendered = render_srt(entries)
    assert "一行目" in rendered
    assert "二行目" in rendered
