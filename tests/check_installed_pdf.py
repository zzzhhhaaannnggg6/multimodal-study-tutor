"""Run outside the checkout using a wheel installed with its [pdf] extra."""

import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import mst
from mst.export import export_study_guide
from mst.jobs import JobManager
from pdf_fixtures import visual_pdf


assert Path(mst.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), mst.__file__
os.environ["PATH"] = ""  # The installed renderer cannot use developer Poppler.
with tempfile.TemporaryDirectory(prefix="mst-installed-pdf-") as temporary:
    manager = JobManager(Path(temporary))
    try:
        original = visual_pdf()
        job = manager.submit([{"name": "synthetic.pdf", "data": base64.b64encode(original).decode()}])
        assert manager.events[job["job_id"]].wait(20)
        record = manager.get(job["job_id"])
        assert record["status"] == "succeeded", record
        assert record["materials"][0]["rendered_page_count"] == 12
        root = manager.active_root()
        guide = json.loads((root / "derived/study-guide.json").read_text())
        assert guide["generation_report"]["status"] == "draft"
        refs = [ref for ref in guide["source_index"] if ref.get("image_path")]
        assert sorted({ref["page"] for ref in refs}) == list(range(1, 13))
        assert any("page 10" in ref.get("quote", "") for ref in refs)
        document = export_study_guide(root, format="html").read_text()
        embedded = re.findall(r'src="data:image/png;base64,([^"]+)"', document)
        assert len(embedded) == 12
        assert base64.b64decode(embedded[0]) == (root / refs[0]["image_path"]).read_bytes()
        assert not re.search(r"<details[^>]*\sopen(?:\s|>)", document)
        assert next((root / "sources").rglob("*.pdf")).read_bytes() == original
    finally:
        manager.close()
print("Installed wheel: 12 actual PDF pages rendered without external tools; HTML carries images offline; original preserved.")
