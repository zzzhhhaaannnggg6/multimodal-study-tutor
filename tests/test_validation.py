"""Focused tests for the dependency-free lesson-map validation gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mst.models import Claim, Evidence, LessonMap
from mst.validation import validate_lesson_map


def valid_map() -> dict:
    return {
        "schema_version": "1.0",
        "map_kind": "lesson-reconstruction",
        "subject": "generic",
        "profile": "generic",
        "sources": [
            {
                "source_id": "slides-01",
                "kind": "slides",
                "name": "intro.pdf",
                "portable_path": "sources/intro.pdf",
            },
            {
                "source_id": "transcript-01",
                "kind": "transcript",
                "name": "lecture.srt",
                "portable_path": "sources/lecture.srt",
            },
        ],
        "visual_sources": [
            {
                "visual_id": "slides-01::p001",
                "source_id": "slides-01",
                "page": 1,
                "title": "Core idea",
                "status": "covered",
            }
        ],
        "media_segments": [
            {
                "segment_id": "transcript-01@000010-000020",
                "media_id": "transcript-01",
                "start": "00:00:10",
                "end": "00:00:20",
                "text": "The teacher explains the core idea.",
                "alignment": {
                    "visual_ids": ["slides-01::p001"],
                    "confidence": "high",
                    "status": "aligned",
                },
            }
        ],
        "units": [
            {
                "unit_id": "unit-01",
                "title": "Core idea",
                "unit_kind": "concept",
                "visual_ids": ["slides-01::p001"],
                "segment_ids": ["transcript-01@000010-000020"],
                "understanding_level": "U3",
                "exam_evidence_level": "E1",
                "logic_chain": "premise -> mechanism -> result",
                "representative_example": "A small example",
                "learner_action": "Explain the mechanism",
                "transfer_question": "How would it change in a new case?",
                "status": "ready",
            }
        ],
        "claims": [
            {
                "claim_id": "claim-01",
                "unit_id": "unit-01",
                "text": "The mechanism follows from the stated premise.",
                "understanding_level": "U3",
                "exam_evidence_level": "E3",
                "status": "verified",
                "sources": [
                    {
                        "evidence_id": "ev-01",
                        "kind": "teacher_quote",
                        "source_id": "transcript-01",
                        "ref": "transcript-01@000010-000020",
                        "quote": "The mechanism follows from the premise.",
                        "start": "00:00:10",
                        "end": "00:00:20",
                        "verified": True,
                    }
                ],
            }
        ],
        "review_items": [
            {
                "review_id": "review-01",
                "unit_id": "unit-01",
                "prompt": "Explain the mechanism without looking.",
            }
        ],
    }


def test_valid_map_passes_and_model_round_trips() -> None:
    data = valid_map()
    report = validate_lesson_map(data)
    assert report.ok, [item.to_dict() for item in report.errors]

    model = LessonMap.from_dict(data)
    assert model.pages[0].visual_id == "slides-01::p001"
    assert model.speech_segments[0].alignment is not None
    assert model.claims[0].sources[0].verified is True
    assert LessonMap.from_dict(model.to_dict()).claims[0].claim_id == "claim-01"


def test_e3_requires_verified_quote_and_locator() -> None:
    data = valid_map()
    data["claims"][0]["sources"] = [{"kind": "teacher_quote", "ref": "unknown"}]
    data["claims"][0]["status"] = "pending"
    report = validate_lesson_map(data)
    codes = {item.code for item in report.diagnostics}
    assert "evidence.quote_required" in codes
    assert {"evidence.unverified", "evidence.verification_missing"} & codes
    assert "evidence.unresolved" in codes


def test_alignment_and_reference_errors_are_reported() -> None:
    data = valid_map()
    data["media_segments"][0]["alignment"] = {
        "visual_ids": ["missing-page"],
        "confidence": "certain",
        "status": "aligned",
    }
    report = validate_lesson_map(data)
    codes = {item.code for item in report.errors}
    assert "alignment.confidence" in codes
    assert "alignment.unknown_visual" in codes


def test_timestamp_start_can_be_open_ended() -> None:
    data = valid_map()
    data["media_segments"][0].pop("end", None)
    report = validate_lesson_map(data)
    assert not any(item.code.startswith("time.") for item in report.errors)


def test_absolute_paths_are_rejected_but_can_be_allowed_for_private_workspace() -> None:
    data = valid_map()
    data["sources"][0]["path"] = "/Users/example/private/intro.pdf"
    report = validate_lesson_map(data)
    assert any(item.code == "privacy.absolute_path" for item in report.errors)
    assert validate_lesson_map(data, allow_absolute_paths=True).ok


def test_unstructured_source_is_not_evidence() -> None:
    data = valid_map()
    data["claims"][0]["sources"] = ["teacher said this"]
    report = validate_lesson_map(data)
    assert any(item.code == "evidence.unstructured" for item in report.errors)


def test_e0_does_not_encode_explicit_exclusion() -> None:
    data = valid_map()
    data["claims"][0]["exam_evidence_level"] = "E0"
    data["claims"][0]["text"] = "This is not assessed and will not be tested."
    report = validate_lesson_map(data)
    assert any(item.code == "assessment.e0_exclusion" for item in report.errors)


def test_json_schema_accepts_fixture_when_jsonschema_is_available() -> None:
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema optional dependency is not installed")
    schema_path = Path(__file__).parents[1] / "schemas" / "lesson-map.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(valid_map())


def test_dataclass_construction_uses_structured_evidence() -> None:
    claim = Claim(
        claim_id="claim-01",
        text="A claim",
        sources=[Evidence(kind="material", ref="p001", quote="A claim", verified=True)],
    )
    assert claim.to_dict()["sources"][0]["kind"] == "material"
