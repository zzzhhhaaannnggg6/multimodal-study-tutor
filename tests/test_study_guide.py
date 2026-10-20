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
    assert {item.kind for item in guide.units[0].practice_items} >= {"retrieval", "process", "transfer"}
    assert len(guide.units[0].worked_examples[0].steps) >= 3
    assert guide.units[0].misconceptions
    assert guide.units[0].source_refs
    markdown = render_markdown(guide)
    assert "先看学习路线" in markdown
    assert "例题框架" in markdown
    assert "展开答案与解析" in markdown
    assert "U3" not in markdown and "E1" not in markdown


def test_study_guide_round_trip_and_validation() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    loaded = StudyGuide.from_dict(json.loads(guide.to_json()))
    report = validate_study_guide(loaded, strict=True)
    assert report.ok, [item.message for item in report.errors]
    assert not report.warnings
    assert loaded.units[0].unit_id == guide.units[0].unit_id


def test_offline_topic_label_is_not_presented_as_a_complete_example() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    example = guide.units[0].worked_examples[0]
    assert example.complete is False
    assert "待补充" in example.title
    assert any(item.endswith(".worked_examples.complete") for item in guide.report.missing_fields)


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


def test_computer_systems_offline_guide_uses_concrete_material_example() -> None:
    lesson = LessonMap.from_dict(
        {
            "subject": "computer-systems",
            "profile": "computer-systems",
            "title": "第一讲",
            "pages": [
                {
                    "visual_id": "slides::p003",
                    "page": 3,
                    "title": "Source Code",
                    "status": "covered",
                    "text": "Source Code -> Executable File int x = 10; x = 2 * x + 15; addi r5, r0, 10 muli r5, r5, 2 addi r5, r5, 15 RISC-V",
                }
            ],
        }
    )
    guide = generate_study_guide(lesson)
    unit = guide.units[0]
    example = unit.worked_examples[0]
    assert unit.title == "从 C 代码到 RISC-V 指令"
    assert example.complete is True
    assert "35" in example.answer
    assert len(unit.practice_items) == 3


def test_visual_review_keeps_text_only_provider_output_as_draft() -> None:
    lesson = LessonMap.from_dict(
        {
            "subject": "computer-systems",
            "profile": "computer-systems",
            "title": "含数据通路图的课",
            "pages": [
                {
                    "visual_id": "slides::p001",
                    "page": 1,
                    "title": "数据通路",
                    "status": "covered",
                    "text": "PC -> ALU -> register",
                    "visual_kind": "diagram",
                    "visual_summary": "检测到流程/连接线索。",
                    "needs_visual_review": True,
                }
            ],
        }
    )
    guide = generate_study_guide(lesson, CompleteProvider())
    assert guide.report.status == "draft"
    assert any("视觉结构" in warning for warning in guide.report.warnings)


def test_unit_sources_are_preserved_when_alignment_is_missing() -> None:
    lesson = LessonMap.from_dict(
        {
            "subject": "generic",
            "title": "有课程来源的单元",
            "units": [
                {
                    "unit_id": "u1",
                    "title": "核心概念",
                    "understanding_level": "U3",
                    "sources": [{"kind": "lesson", "ref": "lesson-01"}],
                }
            ],
        }
    )
    guide = generate_study_guide(lesson)
    assert guide.units[0].source_refs[0].ref == "lesson-01"
    assert any(item.ref == "lesson-01" for item in guide.source_index)
    assert not any(item.endswith(".source_refs") for item in guide.report.missing_fields)
