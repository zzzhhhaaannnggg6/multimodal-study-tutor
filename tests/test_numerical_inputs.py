"""Actual imported file bytes must reach a concrete, source-preserving lesson."""

import base64
import io
import json
import zipfile
from fractions import Fraction

import pytest

from mst.answer_checks import answer_values
from mst.jobs import JobManager
from pdf_fixtures import visual_pdf


def slide_bytes(source):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", f'''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>数的表示</a:t></a:r></a:p><a:p><a:r><a:t>{source}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>''')
    return output.getvalue()


@pytest.mark.parametrize("format, source, expected, changed", [
    ("md", "将二进制 (1101)2 转换为十进制，按位权展开计算。", Fraction(13), Fraction(14)),
    ("pptx", "把二进制（１０１．１）₂转换为十进制", Fraction(11, 2), Fraction(6)),
    ("pdf", "Binary to decimal: -(101)2", Fraction(-5), Fraction(-4)),
])
def test_imported_material_produces_actual_steps_and_checked_practice(tmp_path, format, source, expected, changed):
    if format == "pdf":
        pytest.importorskip("pypdf")
        pytest.importorskip("pypdfium2")
        content = visual_pdf(1, page_text=source)
    elif format == "pptx":
        content = slide_bytes(source)
    else:
        content = ("# 数的表示\n" + source).encode()
    manager = JobManager(tmp_path)
    try:
        job = manager.submit([{"name": "合成数字材料." + format, "data": base64.b64encode(content).decode()}], subject="mathematics")
        assert manager.events[job["job_id"]].wait(20)
        record = manager.get(job["job_id"])
        assert record["status"] == "succeeded", record
        root = manager.active_root()
        guide = json.loads((root / "derived/study-guide.json").read_text())
        assert guide["generation_report"]["status"] == "draft"
        unit = guide["units"][0]
        example = unit["worked_examples"][0]
        assert example["complete"] and len(example["steps"]) >= 3
        assert answer_values(example["answer"], 10) == [expected]
        transfer = next(item for item in unit["practice_items"] if item["kind"] == "transfer")
        assert answer_values(transfer["answer"], 10) == [changed]
        assert any(source in ref.get("quote", "") for ref in unit["source_refs"])
        assert next((root / "sources").rglob("*." + format)).read_bytes() == content
        document = (root / "exports/study-guide.html").read_text()
        assert "展开答案与解析" in document
        assert unit["one_sentence"] in document
    finally:
        manager.close()
