from pathlib import Path

from mst.render import render_visual_source


def test_render_reports_unsupported_sources_without_touching_input(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("course notes", encoding="utf-8")
    result = render_visual_source(source, tmp_path / "rendered")
    assert result.images == []
    assert result.warnings
    assert source.read_text(encoding="utf-8") == "course notes"
