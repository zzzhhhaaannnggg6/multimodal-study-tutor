from pathlib import Path

from mst.extract import parse_timestamped_text


def test_parse_vtt_cues(tmp_path: Path) -> None:
    source = tmp_path / "lecture.vtt"
    source.write_text(
        "WEBVTT\n\n00:00:02.500 --> 00:00:05.000\n先看证据。\n\n"
        "00:00:06.000 --> 00:00:08.000\n再看机制。\n",
        encoding="utf-8",
    )
    rows = parse_timestamped_text(source)
    assert len(rows) == 2
    assert rows[0].start == 2.5
    assert rows[0].end == 5.0
    assert rows[1].text == "再看机制。"
