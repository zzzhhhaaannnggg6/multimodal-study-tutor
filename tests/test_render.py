from pathlib import Path

from mst.render import render_visual_source
from mst.io import write_json


def test_render_reports_unsupported_sources_without_touching_input(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("course notes", encoding="utf-8")
    result = render_visual_source(source, tmp_path / "rendered")
    assert result.images == []
    assert result.warnings
    assert source.read_text(encoding="utf-8") == "course notes"


def test_poppler_page_numbers_are_numeric_and_gaps_do_not_shift_locators(tmp_path, monkeypatch):
    monkeypatch.setattr("mst.render._pdfium_available", lambda: False)
    monkeypatch.setattr("mst.render._tool", lambda name: "/synthetic/pdftoppm")
    def render(command, **kwargs):
        prefix = Path(command[-1])
        for page in (1, 2, 10):
            prefix.with_name(f"page-{page}.png").write_bytes(b"synthetic page")
    monkeypatch.setattr("mst.render.subprocess.run", render)
    source = tmp_path / "source.pdf"; source.write_bytes(b"synthetic")
    result = render_visual_source(source, tmp_path / "rendered")
    assert list(result.page_images) == [1, 2, 10]
    assert [path.name for path in result.images] == ["source-0001.png", "source-0002.png", "source-0010.png"]


def test_timeout_retains_finished_pages_and_terminates_the_worker(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr("mst.render._pdfium_available", lambda: True)
    children = []
    class Pipe:
        def close(self):
            pass
    class TimedOut:
        def __init__(self, command, **kwargs):
            self.dead = False; self.stdin = Pipe(); children.append(self)
            offset = command.index("mst.pdf_render") + 2
            stage = Path(command[offset])
            (stage / "page-0003.png").write_bytes(b"finished page")
            write_json(stage / "render-result.json", {"total_pages": 5, "pages": {"3": "page-0003.png"}, "warnings": []})
        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("synthetic worker", timeout)
            assert self.dead
            return -9
        def poll(self):
            return -9 if self.dead else None
        def kill(self):
            self.dead = True
    monkeypatch.setattr("mst.render.subprocess.Popen", TimedOut)
    source = tmp_path / "source.pdf"; source.write_bytes(b"synthetic")
    result = render_visual_source(source, tmp_path / "rendered")
    assert list(result.page_images) == [3] and children[0].dead
    assert result.total_pages == 5 and any("超时" in warning for warning in result.warnings)
