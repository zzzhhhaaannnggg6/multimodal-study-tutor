"""Reject observable empty teaching without pretending to verify all answers."""

from __future__ import annotations

import copy
import json

import pytest

from mst.guide import Misconception, generate_study_guide, validate_study_guide
from mst.models import KnowledgeUnit, LessonMap, VisualFrame
from mst.teaching import specific_steps, teaching_issues
from test_study_guide import CompleteProvider, FIXTURE


@pytest.mark.parametrize("steps", [
    ["读取 x6 当前值。", "读取 x6 当前值。", "读取 x6 当前值。"],
    ["检查条件", "完成过程", "核对结果"],
    ["检查条件", "完成过程", "从 x6 读出基址 100。"],
])
def test_repeated_or_generic_steps_cannot_make_a_complete_example(steps):
    class EmptyExample(CompleteProvider):
        def complete(self, **kwargs):
            data = json.loads(super().complete(**kwargs))
            data["worked_examples"][0].update(steps=steps, complete=True)
            return json.dumps(data, ensure_ascii=False)

    assert not specific_steps(steps)
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), EmptyExample())
    assert guide.report.status == "draft"
    assert guide.units[0].worked_examples[0].complete is False
    assert guide.units[0].worked_examples[0].steps == steps  # Do not repair by padding.
    assert not validate_study_guide(guide, strict=True).ok


@pytest.mark.parametrize("mutation, issue", [
    (lambda data: [item.update(prompt="这段机制如何连接条件和结果？") for item in data["practice_items"]], "practice_items.repeated_prompts"),
    (lambda data: data["practice_items"][0].update(answer=data["practice_items"][0]["prompt"]), "practice_items.answer_repeats_question"),
    (lambda data: data["practice_items"][0].update(explanation=data["practice_items"][0]["answer"]), "practice_items.explanation_repeats_answer"),
    (lambda data: data["misconceptions"][0].update(correct=data["misconceptions"][0]["wrong"]), "misconceptions.identical_contrast"),
    (lambda data: data.update(tutor_bridge=data["material_explanation"]), "tutor_bridge.repeats_material"),
    (lambda data: data.update(step_chain=["确定材料中的起因"] * 3), "step_chain.repeated"),
    (lambda data: data["practice_items"][1].update(prompt="请按正确顺序写出完成这个知识点时要检查的步骤。"), "practice_items.generic_prompt"),
    (lambda data: data["practice_items"][2].update(answer="先定位被改变的条件，再沿步骤检查它影响的中间过程和最终结果。"), "practice_items.generic_answer"),
])
def test_complete_fields_still_fail_when_they_do_not_teach(mutation, issue):
    class HollowTeaching(CompleteProvider):
        def complete(self, **kwargs):
            data = json.loads(super().complete(**kwargs))
            mutation(data)
            return json.dumps(data, ensure_ascii=False)

    guide = generate_study_guide(LessonMap.from_json(FIXTURE), HollowTeaching())
    assert guide.report.status == "draft"
    assert guide.units[0].status == "draft"
    assert issue in teaching_issues(guide.units[0])
    assert any(field.endswith(issue) for field in guide.report.missing_fields)
    assert not validate_study_guide(guide, strict=True).ok


def test_cross_unit_boilerplate_does_not_pass_as_distinct_explanations():
    lesson = LessonMap(
        pages=[VisualFrame(visual_id="p1", text="摩擦力的方向与相对运动有关。", status="covered"),
               VisualFrame(visual_id="p2", text="动量是质量与速度的乘积。", status="covered")],
        units=[KnowledgeUnit(unit_id="friction", title="判断摩擦力方向", visual_ids=["p1"]),
               KnowledgeUnit(unit_id="momentum", title="计算动量", visual_ids=["p2"])],
    )
    guide = generate_study_guide(lesson, CompleteProvider())
    assert guide.report.status == "draft"
    assert all(unit.status == "draft" for unit in guide.units)
    assert sum(field.endswith("teaching.repeated_explanation") for field in guide.report.missing_fields) == 2
    assert sum(issue.code == "teaching.repeated_explanation" for issue in validate_study_guide(guide, strict=True).errors) == 2


@pytest.mark.parametrize("wrong, correct", [
    ("x+1", "x-1"), ("x=1", "x!=1"), ("x∈A", "x∉A"),
    ("x", "!x"), ("x", "X"), ("1.5", "15"), ("x_1", "x1"),
])
def test_mathematical_and_code_contrasts_are_not_erased(wrong, correct):
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    unit = copy.deepcopy(guide.units[0])
    unit.misconceptions = [Misconception(wrong, correct, "根据已知条件分别核对两个表达式。")]
    assert "misconceptions.identical_contrast" not in teaching_issues(unit)


def test_complete_synthetic_fixture_passes_observable_checks_only():
    # This is a deterministic test fixture, not a claim of subject-expert review.
    guide = generate_study_guide(LessonMap.from_json(FIXTURE), CompleteProvider())
    assert not teaching_issues(guide.units[0])
    assert validate_study_guide(guide, strict=True).ok
