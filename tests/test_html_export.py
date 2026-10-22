"""An exported guide carries its actual pages without reading arbitrary files."""

import base64
import re
from pathlib import Path

import pytest

from mst.export import export_study_guide, guide_image_data
from mst.guide import GuideSourceRef, generate_study_guide
from mst.io import project_paths
from mst.models import LessonMap


FIXTURE = Path(__file__).parents[1] / "examples/minimal_course/lesson-map.json"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=")


def illustrated_guide(project):
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    ref = GuideSourceRef(ref="page-10", kind="material", label="材料依据", page=10,
                         image_path="derived/rendered/合成课件/page-0010.png")
    guide.units[0].source_refs.append(ref)
    guide.source_index.append(ref)
    image = project / ref.image_path
    image.parent.mkdir(parents=True)
    image.write_bytes(PNG)
    guide.write_json(project_paths(project)["study_guide"])
    return guide, ref, image


def test_standalone_html_carries_one_copy_of_each_page_with_answers_folded(tmp_path):
    guide, ref, image = illustrated_guide(tmp_path)
    target = export_study_guide(tmp_path, format="html")
    document = target.read_text()
    assert document.count('src="data:image/png;base64,') == 1
    payload = re.search(r'src="data:image/png;base64,([^"]+)"', document)[1]
    assert base64.b64decode(payload) == image.read_bytes()
    assert 'href="#material-page-1"' in document and "第 10 页" in document
    assert all(" open" not in tag for tag in re.findall(r"<details[^>]*>", document))
    assert str(tmp_path) not in document and ref.image_path not in document
    assert "&lt;script&gt;" not in document
    # Once exported, replacing/removing the local image cannot affect the HTML.
    image.write_bytes(b"changed local source")
    assert target.read_text() == document
    ref.image_path = None
    guide.title = '<script>alert("course data")</script>'
    guide.write_json(project_paths(tmp_path)["study_guide"])
    escaped = export_study_guide(tmp_path, format="html").read_text()
    assert '<script>' not in escaped and "&lt;script&gt;" in escaped


@pytest.mark.parametrize("outside_kind", ["absolute", "traversal", "image-symlink", "root-symlink", "nested-symlink"])
def test_export_never_embeds_an_image_outside_the_course(tmp_path, outside_kind):
    project = tmp_path / "course"
    guide, ref, image = illustrated_guide(project)
    private = tmp_path / "private.png"
    private.write_bytes(PNG + b"private-should-never-leak")
    if outside_kind == "absolute":
        ref.image_path = str(private)
    elif outside_kind == "traversal":
        ref.image_path = "derived/rendered/../../../private.png"
    elif outside_kind == "image-symlink":
        image.unlink(); image.symlink_to(private)
    elif outside_kind == "nested-symlink":
        (image.parent / "other").symlink_to(tmp_path, target_is_directory=True)
        ref.image_path = "derived/rendered/合成课件/other/private.png"
    else:
        image.unlink(); image.parent.rmdir(); image.parent.parent.rmdir()
        (project / "derived/rendered").symlink_to(tmp_path, target_is_directory=True)
        ref.image_path = "derived/rendered/private.png"
    images, notes = guide_image_data(project, guide)
    assert images == {} and notes and "缺失或无法打包" in notes[0]
    assert str(private) not in "".join(notes)


@pytest.mark.parametrize("problem", ["missing", "invalid", "single-limit", "total-limit"])
def test_missing_invalid_and_oversize_previews_stay_explicit(tmp_path, monkeypatch, problem):
    guide, ref, image = illustrated_guide(tmp_path)
    if problem == "missing":
        image.unlink()
    elif problem == "invalid":
        image.write_bytes(b"<svg onload=alert(1)>")
    else:
        monkeypatch.setattr("mst.export.HTML_SINGLE_IMAGE_LIMIT" if problem == "single-limit" else "mst.export.HTML_IMAGE_BUDGET", len(PNG) - 1)
    target = export_study_guide(tmp_path, format="html")
    document = target.read_text()
    assert "data:image/" not in document
    assert "原页预览不完整" in document and "第 10 页的图像未嵌入" in document
    assert "超出导出大小上限" in document if problem.endswith("limit") else "缺失或无法打包" in document
    assert "<svg" not in document
