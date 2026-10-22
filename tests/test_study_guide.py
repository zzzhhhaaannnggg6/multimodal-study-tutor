from __future__ import annotations

import json
from pathlib import Path

import pytest

from mst.guide import StudyGuide, _teacher_reading, generate_study_guide, render_html, render_markdown, validate_study_guide
from mst.models import Alignment, LessonMap, SpeechSegment, VisualFrame


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
                "worked_examples": [{"title": "完整例题", "question": "如何解释材料给出的新案例？", "setup": "已知材料记录了起因、事件经过和结果，要求解释它们的关系。", "steps": ["把记录中的起因作为候选条件。", "用事件经过中的证据说明该条件如何作用。", "将得到的预测与材料中的实际结果比较，检查有无矛盾。"], "answer": "由条件经机制得到结果，再用记录核对。", "variation": "如果事件经过出现一条相反证据，应回到机制这一步重新判断。", "complete": True}],
                "misconceptions": [{"wrong": "先后发生就等于因果。", "correct": "还需要机制和证据。", "correction": "检查事件经过是否支持提出的因果路径。"}],
                "practice_items": [
                    {"practice_id": "p1", "kind": "retrieval", "prompt": "机制有什么作用？", "answer": "连接证据和结果。", "explanation": "没有机制就不能解释条件如何影响结果。"},
                    {"practice_id": "p2", "kind": "process", "prompt": "比较候选机制与材料时先做什么？", "answer": "先写出该机制预测的结果，再与实际结果比较。", "explanation": "如果二者矛盾，就需要修改或放弃这个候选机制。"},
                    {"practice_id": "p3", "kind": "transfer", "prompt": "新材料只改了一个前提，能直接照搬结论吗？", "answer": "不能，先检查机制是否仍然适用。", "explanation": "结论依赖前提，新条件可能使原机制失效。"}
                ],
            },
            ensure_ascii=False,
        )


def test_generate_student_guide_is_readable_and_traceable() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE))
    assert guide.report.status == "draft"
    assert guide.route.chain == ["从证据到机制"]
    assert guide.units[0].content_mode == "material-only"
    assert not guide.units[0].worked_examples
    assert not guide.units[0].practice_items
    assert not guide.review_items
    assert not guide.units[0].misconceptions
    assert guide.units[0].source_refs
    markdown = render_markdown(guide)
    assert "先看学习路线" in markdown
    assert "精讲待补充" in markdown
    assert "例题框架" not in markdown
    assert "展开答案与解析" not in markdown
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
    assert not guide.units[0].worked_examples
    assert any(item.endswith(".worked_examples") for item in guide.report.missing_fields)


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
    assert "21" in unit.practice_items[2].answer
    assert "旧 r5" in unit.practice_items[0].prompt
    assert "先计算右侧" in " ".join(unit.prerequisites)
    assert "不是标准 RISC-V" in example.setup
    assert "r5 从 0" not in " ".join(example.steps)


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


def test_pending_speech_is_visible_in_report_but_not_in_teacher_explanation() -> None:
    segment = SpeechSegment(segment_id="s1", text="注意不要把多周期控制器状态机作为本节入门知识。", status="pending",
                            alignment=Alignment(visual_ids=["p1"], confidence="low", status="pending"))
    lesson = LessonMap(pages=[VisualFrame(visual_id="p1", page=1, title="入门", text="CPU 和内存", status="covered")], speech_segments=[segment])
    guide = generate_study_guide(lesson)
    assert "多周期控制器" not in guide.units[0].teacher_increment
    assert guide.report.pending_segments == 1
    assert guide.report.unresolved_items == ["s1"]
    ref = next(ref for ref in guide.source_index if ref.ref == "s1")
    assert ref.label == "语音配对待确认" and ref.verified is False
    assert "语音配对待确认：1" in render_html(guide)
    assert "展开材料与语音来源索引" in render_markdown(guide)
    assert segment.text in render_html(guide)  # Available in the appendix.
    assert StudyGuide.from_dict(json.loads(guide.to_json())).report.pending_segments == 1


def test_teacher_addition_keeps_corrections_and_readable_honest_times() -> None:
    segments = [SpeechSegment(text="这里提供额外的说明，帮助大家区分课堂涉及的不同对象。", start=i) for i in range(6)]
    segments.append(SpeechSegment(text="注意不要把内存的地址当成这个位置存储的数据。", start=135.5, end=140, metadata={"end_inferred": True}))
    text = _teacher_reading(segments)
    assert "注意不要把内存" in text
    assert "00:02:15.5 起；结束时间未标注" in text
    assert "135.5" not in text and "00:02:20" not in text


def test_c_code_alone_does_not_invent_a_riscv_translation() -> None:
    guide = generate_study_guide(LessonMap(profile="computer-systems", pages=[VisualFrame(visual_id="p1", text="int x = 10; x = 2 * x + 15;", status="covered")]))
    assert not guide.units[0].worked_examples
    assert guide.units[0].content_mode == "material-only"


def test_short_provider_answer_is_not_padded_into_a_complete_lesson() -> None:
    class ShortProvider(CompleteProvider):
        def complete(self, **kwargs) -> str:
            data = json.loads(super().complete(**kwargs))
            data["worked_examples"][0].update(setup="", steps=["检查条件"], variation="")
            data["practice_items"] = data["practice_items"][:1]
            return json.dumps(data, ensure_ascii=False)

    guide = generate_study_guide(LessonMap.from_json(FIXTURE), ShortProvider())
    assert guide.report.status == "draft"
    assert guide.units[0].worked_examples[0].steps == ["检查条件"]
    assert guide.units[0].worked_examples[0].complete is False
    assert len(guide.units[0].practice_items) == 1
    assert any(field.endswith("practice_items>=3") for field in guide.report.missing_fields)
    assert not validate_study_guide(guide, strict=True).ok


def test_provider_cannot_override_teacher_or_assessment_evidence() -> None:
    class UnsupportedClaims(CompleteProvider):
        def complete(self, **kwargs) -> str:
            data = json.loads(super().complete(**kwargs))
            data.update(teacher_increment="老师承诺这道题必考。", assessment_signal="这道题必考")
            return json.dumps(data, ensure_ascii=False)

    lesson = LessonMap.from_json(FIXTURE)
    expected = generate_study_guide(lesson).units[0]
    actual = generate_study_guide(lesson, UnsupportedClaims()).units[0]
    assert actual.teacher_increment == expected.teacher_increment
    assert actual.assessment_signal == expected.assessment_signal


def test_provider_receives_full_page_text_beyond_reader_preview() -> None:
    class CaptureProvider(CompleteProvider):
        def complete(self, **kwargs) -> str:
            prompt = json.loads(kwargs["user"])
            context = json.loads(prompt["source_context"])
            assert context["pages"][0]["text"].endswith("最后一条关键限制")
            assert len(context["pages"][0]["text"]) > 260
            return super().complete(**kwargs)

    lesson = LessonMap(pages=[VisualFrame(visual_id="p1", text="说明内容。" * 100 + "最后一条关键限制", status="covered")])
    guide = generate_study_guide(lesson, CaptureProvider())
    assert not any("模型补全失败" in warning for warning in guide.report.warnings)


def test_new_report_fields_keep_json_schema_compatibility() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((FIXTURE.parents[2] / "schemas" / "study-guide.schema.json").read_text())
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    jsonschema.Draft202012Validator(schema).validate(guide.to_dict())


def test_html_review_has_return_link_and_source_quotes_are_escaped() -> None:
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    guide.source_index[0].quote = '<script>alert("source data")</script>'
    document = render_html(guide)
    assert f'id="{guide.units[0].unit_id}"' in document
    assert f'href="#{guide.units[0].unit_id}"' in document
    assert "回到对应讲解" in document
    assert '<script>alert("source data")</script>' not in document
    assert "&lt;script&gt;" in document


def test_provider_cannot_invent_example_source_locators() -> None:
    class InventedSource(CompleteProvider):
        def complete(self, **kwargs) -> str:
            data = json.loads(super().complete(**kwargs))
            data["worked_examples"][0]["source_refs"] = [{"ref": "invented-page", "kind": "teacher", "page": 999, "verified": True}]
            return json.dumps(data, ensure_ascii=False)

    guide = generate_study_guide(LessonMap.from_json(FIXTURE), InventedSource())
    assert guide.report.status == "draft"
    assert guide.units[0].status == "draft"
    assert all(ref.ref != "invented-page" for ref in guide.units[0].worked_examples[0].source_refs)
    assert any("未提供的来源" in warning for warning in guide.report.warnings)


def test_material_only_view_preserves_every_page_without_fake_learning_tasks():
    pages = [VisualFrame(visual_id=f"p{i}", page=i, title="待展开的主题", text=("材料细节。" * 70) + f"第{i}页末尾条件", status="covered") for i in range(1, 5)]
    lesson = LessonMap(pages=pages)
    before = lesson.to_dict()
    guide = generate_study_guide(lesson)
    unit = guide.units[0]
    assert unit.content_mode == "material-only"
    assert not unit.worked_examples and not unit.practice_items and not unit.tutor_bridge
    assert not guide.route.outcomes and guide.route.estimated_minutes == 0
    for document in (render_markdown(guide), render_html(guide)):
        assert "精讲待补充" in document
        assert all(f"第{i}页末尾条件" in document for i in range(1, 5))
        assert "只改变一个条件后" not in document
        assert "先确定被改变的条件" not in document
        assert "展开答案与解析" not in document
    assert lesson.to_dict() == before
    assert StudyGuide.from_dict(json.loads(guide.to_json())).units[0].content_mode == "material-only"
    assert not validate_study_guide(guide, strict=True).ok


def test_provider_failure_keeps_material_only_but_real_explanation_opens_teaching_view():
    class Unavailable:
        def complete(self, **kwargs):
            raise RuntimeError("synthetic unavailable")
    lesson = LessonMap.from_json(FIXTURE)
    failed = generate_study_guide(lesson, Unavailable())
    assert failed.units[0].content_mode == "material-only"
    assert not failed.review_items
    explained = generate_study_guide(lesson, CompleteProvider())
    assert explained.units[0].content_mode == "lesson"
    assert explained.review_items
    assert "展开答案与解析" in render_html(explained)


def test_mixed_course_review_contains_only_actual_exercises():
    guide = generate_study_guide(LessonMap(profile="mathematics", pages=[
        VisualFrame(visual_id="p1", page=1, title="进制", text="Binary to decimal: (1101)2", status="covered"),
        VisualFrame(visual_id="p2", page=2, title="证明", text="有界单调数列的收敛性尚待展开。", status="covered"),
    ]))
    assert [unit.content_mode for unit in guide.units] == ["lesson", "material-only"]
    assert guide.review_items and {item.unit_id for item in guide.review_items} == {guide.units[0].unit_id}
    assert len(guide.route.outcomes) == 1
    assert "(13)₁₀" in render_html(guide)


def test_material_view_keeps_aligned_teacher_addition_and_rejects_fake_completion():
    lesson = LessonMap(pages=[VisualFrame(visual_id="p1", page=4, title="因果解释", text="观察到的先后顺序与因果关系。", status="covered")],
        speech_segments=[SpeechSegment(segment_id="s1", text="注意先后顺序不能直接证明因果关系，需要另外检查作用过程。", start=12, end=18, status="verified",
            alignment=Alignment(visual_ids=["p1"], status="aligned"))])
    guide = generate_study_guide(lesson)
    assert guide.units[0].content_mode == "material-only"
    for document in (render_markdown(guide), render_html(guide)):
        assert "另外检查作用过程" in document
        assert "00:00:12" in document
    guide.units[0].status = "ready"
    guide.report.status = "complete"
    assert any(issue.code == "unit.material_only" for issue in validate_study_guide(guide, strict=True).errors)
