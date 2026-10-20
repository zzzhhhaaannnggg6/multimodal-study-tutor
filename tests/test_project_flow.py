from __future__ import annotations

import json
from pathlib import Path

from mst.agent import StudyAgent
from mst.ingest import ingest_project, init_project
from mst.io import project_paths
from mst.models import LessonMap
from mst.reconstruct import build_scaffold
from mst.validation import validate_lesson_map


def test_fixture_is_traceable() -> None:
    fixture = Path(__file__).parents[1] / "examples" / "minimal_course" / "lesson-map.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    report = validate_lesson_map(data, strict=True)
    assert report.ok, [item.to_dict() for item in report.errors]
    assert len(report.map.pages) == 2
    assert len(report.map.claims) == 1


def test_ingest_and_scaffold_do_not_require_model(tmp_path: Path) -> None:
    project = tmp_path / "project"
    init_project(project, "generic")
    source = tmp_path / "lesson.txt"
    source.write_text("synthetic lesson", encoding="utf-8")
    manifest = ingest_project(project, [source])
    assert manifest["source_manifest"][0]["sha256"]
    result = build_scaffold(project)
    assert result["notes"]["status"] == "scaffold"
    assert project_paths(project)["lesson_map"].exists()


def test_scaffold_records_visual_signals_and_speech_alignment(tmp_path: Path) -> None:
    project = tmp_path / "multimodal-project"
    init_project(project, "computer-systems")
    slides = tmp_path / "slides.md"
    slides.write_text("# 数据通路\nPC -> ALU -> 寄存器\naddi x5, x0, 10\n", encoding="utf-8")
    transcript = tmp_path / "lecture.vtt"
    transcript.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
        "数据通路中 PC 经过 ALU 后写回寄存器。\n",
        encoding="utf-8",
    )
    ingest_project(project, [slides, transcript])
    data = build_scaffold(project)
    assert data["pages"][0]["visual_kind"] in {"code", "diagram", "mixed"}
    segment = data["speech_segments"][0]
    assert segment["alignment"]["visual_ids"] == [data["pages"][0]["visual_id"]]
    assert segment["metadata"]["speech_analysis"]["primary_role"] == "general"


def test_agent_keeps_query_grounded() -> None:
    fixture = Path(__file__).parents[1] / "examples" / "minimal_course" / "lesson-map.json"
    agent = StudyAgent(LessonMap.from_json(fixture))
    hits = agent.query_claims("机制")
    assert hits and hits[0]["claim_id"] == "claim::model"
    assert "claim::model" in agent.explain("机制")
