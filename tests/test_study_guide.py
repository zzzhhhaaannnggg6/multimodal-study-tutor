from __future__ import annotations

import json
from pathlib import Path

from mst.guide import StudyGuide, generate_study_guide, render_markdown, validate_study_guide
from mst.models import LessonMap


FIXTURE = Path(__file__).parents[1] / "examples" / "minimal_course" / "lesson-map.json"


class CompleteProvider:
    name = "test-provider"

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        del system, user, response_format
        return json.dumps(
            {
                "one_sentence": "用证据、机制和结果组成完整解释。",
                "why": "机制决定结论能否迁移到新案例。",
                "material_explanation": "先看材料给出的事实，再看过程。",
                "teacher_increment": "老师提醒先找事实。",
                "tutor_bridge": "证据是起点，机制把它连接到结果。",
                "step_chain": ["找证据", "写机制", "查结果"],
                "worked_examples": [{"title": "完整例题", "question": "如何解释新案例？", "steps": ["找证据", "写机制"], "answer": "完成三步解释。", "variation": "改变条件后重查机制。", "complete": True}],
                "misconceptions": [],
                "practice_items": [{"practice_id": "p1", "prompt": "机制有什么作用？", "answer": "连接证据和结果。", "explanation": "没有机制就不能迁移。"}],
            },
            ensure_ascii=False,
        )


def test_generate_student_guide_is_readable_and_traceable() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    assert guide.report.status == "draft"
    assert guide.route.chain == ["从证据到机制"]
    assert guide.units[0].worked_examples
    assert guide.units[0].practice_items[0].answer
    assert guide.units[0].source_refs
    markdown = render_markdown(guide)
    assert "先看学习路线" in markdown
    assert "完整例题" in markdown
    assert "展开答案与解析" in markdown
    assert "U3" not in markdown and "E1" not in markdown


def test_study_guide_round_trip_and_validation() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    loaded = StudyGuide.from_dict(json.loads(guide.to_json()))
    report = validate_study_guide(loaded, strict=True)
    assert report.ok, [item.message for item in report.errors]
    assert report.warnings
    assert loaded.units[0].unit_id == guide.units[0].unit_id


def test_incomplete_core_unit_is_rejected() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    guide.units[0].source_refs = []
    report = validate_study_guide(guide, strict=True)
    assert not report.ok
    assert any(item.code == "unit.incomplete" for item in report.errors)


def test_provider_can_upgrade_a_draft_to_complete_guide() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    assert guide.report.status == "complete"
    assert guide.report.provider == "test-provider"
    assert guide.units[0].worked_examples[0].complete is True
    assert validate_study_guide(guide, strict=True).ok
