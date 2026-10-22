"""Actual native PDF rendering, ordering, bounds and publication boundaries."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")
pytest.importorskip("pypdf")

from PIL import Image
from mst.extract import extract_pdf_pages
from mst.guide import generate_study_guide
from mst.ingest import ingest_project, init_project
from mst.jobs import JobManager
from mst.materials import material_results
from mst.models import LessonMap
from mst.pdf_render import MAX_EDGE, MAX_PIXELS, render_pages
from mst.reconstruct import build_scaffold
from mst.render import render_visual_source
from pdf_fixtures import visual_pdf
from test_jobs import uploads


def pdf_upload(content, name="合成课件.pdf"):
    return {"name": name, "data": base64.b64encode(content).decode()}


def test_all_twelve_real_pages_have_their_own_image_and_locator_without_system_tools(tmp_path, monkeypatch):
    source = tmp_path / "Synthetic.pdf"
    source.write_bytes(visual_pdf())
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("PATH", "")
    result = render_visual_source(source, tmp_path / "rendered")
    assert result.renderer == "pdfium" and result.total_pages == 12 and not result.warnings
    assert list(result.page_images) == list(range(1, 13))
    assert [image.name for image in result.images][1:3] == ["Synthetic-0002.png", "Synthetic-0003.png"]
    for number, path in result.page_images.items():
        with Image.open(path) as image:
            assert image.size == (500, 334)
            pixel = image.convert("RGB").getpixel((100, 200))
            assert pixel == ((255, 0, 0) if number % 2 else (0, 0, 255)), (number, pixel)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    project = tmp_path / "course"
    init_project(project, subject="physics")
    ingest_project(project, [source])
    data = build_scaffold(project, render=True)
    for number, page in enumerate(data["pages"], 1):
        assert page["page"] == number and f"page {number:02d}" in page["text"]
        assert page["image_path"].endswith(f"-{number:04d}.png")
        assert page["needs_visual_review"] is True
    guide = generate_study_guide(LessonMap.from_dict(data))
    assert guide.report.visual_review_pages == 12 and guide.report.status != "complete"
    assert len([ref for ref in guide.source_index if ref.image_path]) == 12


def test_rotation_crop_and_giant_page_stay_bounded(tmp_path):
    source = tmp_path / "geometry.pdf"
    source.write_bytes(visual_pdf(3, rotate_page=1, crop_page=2, huge_page=3))
    result = render_visual_source(source, tmp_path / "rendered")
    assert not result.warnings
    with Image.open(result.page_images[1]) as image:
        assert image.width < image.height
    with Image.open(result.page_images[2]) as image:
        assert image.width < 500 and image.height < 334
    with Image.open(result.page_images[3]) as image:
        assert max(image.size) <= MAX_EDGE and image.width * image.height <= MAX_PIXELS


def test_preview_limits_preserve_numbering_and_warn_in_guide_and_receipt(tmp_path, monkeypatch):
    source = tmp_path / "limits.pdf"; source.write_bytes(visual_pdf(3))
    result = render_visual_source(source, tmp_path / "rendered", page_limit=2)
    assert result.total_pages == 3 and list(result.page_images) == [1, 2]
    assert any("前 2 页" in warning for warning in result.warnings)
    tiny = render_visual_source(source, tmp_path / "tiny", byte_limit=1)
    assert not tiny.images and any("保存上限" in warning for warning in tiny.warnings)
    monkeypatch.setattr("mst.reconstruct.MAX_PREVIEW_PAGES_PER_RUN", 2)
    project = tmp_path / "course"; init_project(project)
    ingest_project(project, [source])
    data = build_scaffold(project, render=True)
    guide = generate_study_guide(LessonMap.from_dict(data))
    assert any("前 2 页" in warning for warning in guide.report.warnings)
    receipt = material_results(project, [{"name": source.name, "stored_name": source.name, "size_bytes": source.stat().st_size}])[0]
    assert receipt["page_count"] == 3 and receipt["rendered_page_count"] == 2
    assert any("前 2 页" in warning for warning in receipt["preview_notes"])


def test_one_failed_page_cannot_shift_a_later_page_to_the_wrong_source(tmp_path, monkeypatch):
    import pypdfium2
    original = pypdfium2.PdfDocument.__getitem__
    def unreadable_second(document, index):
        if index == 1:
            raise ValueError("synthetic page failure")
        return original(document, index)
    monkeypatch.setattr(pypdfium2.PdfDocument, "__getitem__", unreadable_second)
    source = tmp_path / "source.pdf"; source.write_bytes(visual_pdf(3))
    output = tmp_path / "worker"
    report = render_pages(source, output)
    assert set(report["pages"]) == {"1", "3"}
    assert any("第 2 页" in warning for warning in report["warnings"])
    assert (output / report["pages"]["3"]).name == "page-0003.png"


def test_repeated_render_never_reuses_a_stale_page_as_current_evidence(tmp_path):
    source = tmp_path / "same.pdf"; source.write_bytes(visual_pdf(3))
    first = render_visual_source(source, tmp_path / "rendered")
    assert len(first.images) == 3
    source.write_bytes(b"broken PDF, not a page")
    second = render_visual_source(source, tmp_path / "rendered")
    assert second.page_images == {} and second.warnings


def test_scan_is_previewable_after_failure_without_replacing_a_saved_lesson(tmp_path):
    manager = JobManager(tmp_path)
    try:
        first = manager.submit(uploads())
        assert manager.events[first["job_id"]].wait(10)
        saved = manager.active_root()
        scan = manager.submit([pdf_upload(visual_pdf(2, text=False))])
        assert manager.events[scan["job_id"]].wait(10)
        scan = manager.get(scan["job_id"])
        assert scan["status"] == "failed" and manager.active_root() == saved
        receipt = scan["materials"][0]
        assert receipt["status"] == "no-text" and receipt["text_page_count"] == 0
        assert receipt["rendered_page_count"] == 2 and len(receipt["preview_pages"]) == 2
        assert "图示" in receipt["detail"]
        for preview in receipt["preview_pages"]:
            assert (manager.directory / scan["job_id"] / "workspace" / preview["image_path"]).exists()
    finally:
        manager.close()


def test_encrypted_or_broken_pdf_keeps_good_sources_and_reports_separate_reading_failure(tmp_path):
    from pypdf import PdfWriter
    import io
    writer = PdfWriter(); writer.add_blank_page(300, 200); writer.encrypt("synthetic-password")
    data = io.BytesIO(); writer.write(data)
    manager = JobManager(tmp_path)
    try:
        job = manager.submit([*uploads(), pdf_upload(data.getvalue(), "加密.pdf"), pdf_upload(b"bad PDF", "损坏.pdf")])
        assert manager.events[job["job_id"]].wait(10)
        record = manager.get(job["job_id"])
        assert record["status"] == "succeeded", record
        assert [row["status"] for row in record["materials"]] == ["text-read", "unreadable", "unreadable"]
        assert all(row["preview_notes"] for row in record["materials"][1:])
        guide = json.loads((manager.active_root() / "derived/study-guide.json").read_text())
        assert guide["generation_report"]["status"] == "draft"
        assert any("密码" in row for row in guide["generation_report"]["warnings"])
    finally:
        manager.close()


def test_native_worker_stops_when_its_parent_pipe_closes(tmp_path):
    source = tmp_path / "many.pdf"; source.write_bytes(visual_pdf(200))
    output = tmp_path / "worker"
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.Popen([sys.executable, "-m", "mst.pdf_render", str(source), str(output), "--watch-parent"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
    try:
        deadline = time.monotonic() + 10
        while not (output / "render-result.json").exists() and time.monotonic() < deadline:
            assert child.poll() is None
            time.sleep(0.02)
        assert child.poll() is None
        child.stdin.close()
        assert child.wait(5) == 3
    finally:
        if child.poll() is None:
            child.kill(); child.wait(5)
