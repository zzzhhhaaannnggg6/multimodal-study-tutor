from mst.io import project_paths, write_json
from mst.materials import material_results


def test_receipt_counts_empty_pages_and_pending_speech_without_claiming_teaching_coverage(tmp_path):
    files = [{"stored_name": "001-scan.pdf", "name": "扫描课件.pdf", "size_bytes": 10},
             {"stored_name": "002-talk.txt", "name": "转写.txt", "size_bytes": 10}]
    paths = project_paths(tmp_path)
    write_json(paths["manifest"], {"source_manifest": [{"name": file["stored_name"], "source_id": str(i), "kind": kind}
               for i, (file, kind) in enumerate(zip(files, ["reading", "transcript"]))]})
    write_json(paths["lesson_map"], {"pages": [{"source_id": "0", "page": 1, "text": "内容"}, {"source_id": "0", "page": 2, "text": ""}],
               "speech_segments": [{"source_id": "1", "text": "普通转写", "alignment": {"status": "pending"}},
                                   {"source_id": "1", "text": "课堂事务", "alignment": {"status": "navigation"}}]})
    receipt, transcript = material_results(tmp_path, files)
    assert receipt["status"] == "partial" and receipt["page_count"] == 2 and receipt["text_page_count"] == 1
    assert "图表和公式仍需核对" in receipt["detail"]
    assert transcript["pending_segment_count"] == transcript["navigation_segment_count"] == 1
    assert transcript["timed_segment_count"] == 0 and "不能定位" in transcript["action"]
    write_json(paths["lesson_map"], {"pages": [{"source_id": "0", "page": 1, "text": ""}]})
    assert material_results(tmp_path, files)[0]["status"] == "no-text"


def test_invalid_receipt_data_does_not_prevent_reopening_saved_jobs(tmp_path):
    files = [{"stored_name": "001-课件.md", "name": "课件.md", "size_bytes": 10}]
    paths = project_paths(tmp_path)
    write_json(paths["manifest"], {})
    write_json(paths["lesson_map"], [])
    assert material_results(tmp_path, files)[0]["status"] == "pending"
    write_json(paths["lesson_map"], {"pages": None, "speech_segments": [None], "notes": None})
    assert material_results(tmp_path, files)[0]["status"] == "no-text"
