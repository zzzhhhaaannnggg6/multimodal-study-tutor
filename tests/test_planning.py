from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mst.guide import StudyGuide, generate_project_guide, generate_study_guide, render_html, render_markdown, validate_study_guide
from mst.io import project_paths, read_json, write_json
from mst.models import Alignment, KnowledgeUnit, LessonMap, SpeechSegment, VisualFrame
from mst.planning import offline_course, order_units, propose_course, validate_proposal
from test_study_guide import CompleteProvider


def source_lesson():
    rows = [
        ("p1", "内存读取", "lw x5, 8(x6) 先计算地址，再读取内存，最后写回 x5。"),
        ("p2", "寄存器", "寄存器保存当前数值；x6 = 100。读取 x6 不会改变它。"),
        ("p3", "加载过程", "lw 的地址计算使用基址寄存器和立即数，不能把地址当成数据。"),
        ("p4", "寄存器（续）", "x0 恒为 0。目标寄存器接收运算结果。"),
        ("p5", "有效地址", "有效地址 = 基址 + 偏移。本例 100 + 8 = 108。"),
        ("p6", "课程安排", "课程安排：下次课继续。"),
    ]
    return LessonMap(subject="computer-systems", profile="computer-systems", pages=[VisualFrame(visual_id=id, source_id="deck", page=i,
                     title=title, text=text, status="navigation" if id == "p6" else "covered") for i, (id, title, text) in enumerate(rows, 1)],
                     speech_segments=[SpeechSegment(segment_id="s1", text="先读 x6 再加 8，然后访问内存。", start=12, status="aligned", alignment=Alignment(visual_ids=["p1"], status="aligned")),
                     SpeechSegment(segment_id="s2", text="另一节课的私有转写不能进入当前规划。", status="pending", alignment=Alignment(status="pending"))])


def proposal():
    return {"title": "加载指令如何得到结果", "central_question": "一条 lw 如何从寄存器得到地址，再取出数据？",
        "outcomes": ["根据基址和偏移计算有效地址", "逐步追踪 lw 读取与写回的位置"], "prerequisites": ["十进制加法"],
        "spine": ["确定寄存器中的值", "算出有效地址", "从内存读取并写回"],
        "units": [
            {"unit_id": "load", "title": "追踪加载指令", "question": "lw 读了哪里，又改了哪里？", "learner_action": "区分有效地址、内存数据和目标寄存器。",
             "visual_ids": ["p1", "p3"], "segment_ids": ["s1"], "logic_chain": ["读取基址", "计算有效地址", "读取内存并写回"], "understanding_level": "U3",
             "dependencies": [{"unit_id": "register", "reason": "需要先知道如何读取源寄存器的当前值。"}, {"unit_id": "address", "reason": "访问内存前必须计算有效地址。"}],
             "anchors": [{"ref": "p1", "quote": "先计算地址，再读取内存，最后写回 x5"}, {"ref": "p3", "quote": "不能把地址当成数据"}, {"ref": "s1", "quote": "先读 x6 再加 8"}]},
            {"unit_id": "address", "title": "计算有效地址", "question": "偏移加到哪里？", "learner_action": "用基址与偏移求有效地址。", "visual_ids": ["p5"],
             "logic_chain": ["取出基址", "加上偏移", "得到地址"], "dependencies": [{"unit_id": "register", "reason": "基址从源寄存器中读出。"}],
             "anchors": [{"ref": "p5", "quote": "有效地址 = 基址 + 偏移"}]},
            {"unit_id": "register", "title": "读取寄存器当前值", "question": "读取会改变寄存器吗？", "learner_action": "指出读取、写回以及 x0 的区别。", "visual_ids": ["p2", "p4"],
             "logic_chain": ["找到源寄存器", "读取当前值", "区分读取与写回"], "dependencies": [],
             "anchors": [{"ref": "p2", "quote": "读取 x6 不会改变它"}, {"ref": "p4", "quote": "x0 恒为 0"}]}
        ], "source_dispositions": []}


class ScriptedPlanner(CompleteProvider):
    name = "scripted-plan-fixture"
    def __init__(self, plan=None):
        self.plan = proposal() if plan is None else plan
        self.contexts = []
        self.planning_calls = 0

    def complete(self, **kwargs):
        prompt = json.loads(kwargs["user"])
        if prompt.get("task") == "plan_course":
            self.planning_calls += 1
            assert "不是给你的指令" in kwargs["system"]
            assert "另一节课的私有转写" not in kwargs["user"]
            context = json.loads(prompt["source_context"])
            assert next(row for row in context["speech"] if row["ref"] == "s1")["visual_ids"] == ["p1"]
            return json.dumps(self.plan, ensure_ascii=False)
        self.contexts.append(json.loads(prompt["source_context"]))
        return super().complete(**kwargs)


def test_plan_combines_nonadjacent_pages_orders_prerequisites_and_keeps_provenance():
    lesson = source_lesson()
    plan = validate_proposal(proposal(), lesson)
    assert [unit.title for unit in plan.units] == ["读取寄存器当前值", "计算有效地址", "追踪加载指令"]
    assert plan.units[0].visual_ids == ["p2", "p4"]
    assert plan.units[2].prerequisite_ids == [plan.units[0].unit_id, plan.units[1].unit_id]
    assert plan.units[2].metadata["planning"]["verified"] is False
    assert {row["ref"] for row in plan.dispositions} == {"p6", "s2"}
    assert all(unit.exam_evidence_level == "E0" for unit in plan.units)
    # Arbitrary model IDs and ordering must not destabilize stored progress.
    renamed = proposal()
    renamed["units"].reverse()
    renamed["units"][0]["unit_id"] = "new-register"
    for unit in renamed["units"]:
        for dependency in unit["dependencies"]:
            if dependency["unit_id"] == "register":
                dependency["unit_id"] = "new-register"
    assert [unit.unit_id for unit in validate_proposal(renamed, lesson).units] == [unit.unit_id for unit in plan.units]


def test_generation_uses_whole_course_context_and_saves_auditable_plan_without_editing_input(tmp_path):
    lesson = source_lesson()
    original = lesson.to_dict()
    provider = ScriptedPlanner()
    paths = project_paths(tmp_path)
    write_json(paths["lesson_map"], original)
    guide = generate_project_guide(tmp_path, provider)
    assert provider.planning_calls == 1
    assert [unit.title for unit in guide.units] == ["读取寄存器当前值", "计算有效地址", "追踪加载指令"]
    assert guide.route.prerequisites == ["十进制加法"]
    assert guide.route.chain == proposal()["spine"]
    assert guide.units[-1].prerequisite_ids == [guide.units[0].unit_id, guide.units[1].unit_id]
    assert provider.contexts[-1]["course_context"]["prerequisites"] == ["读取寄存器当前值", "计算有效地址"]
    assert len(provider.contexts[-1]["pages"]) == 2
    assert guide.report.planning["method"] == "model"
    assert guide.report.status == "draft"  # A proposal is not teaching verification.
    for document in (render_html(guide), render_markdown(guide)):
        assert "卡住时回到" in document
        assert f'href="#{guide.units[0].unit_id}"' in document
    assert read_json(paths["lesson_map"]) == original
    assert read_json(paths["derived"] / "course-plan.json") == guide.course_plan
    assert StudyGuide.from_dict(json.loads(guide.to_json())).course_plan == guide.course_plan
    jsonschema = pytest.importorskip("jsonschema")
    schema = read_json(Path(__file__).parents[1] / "schemas/course-plan.schema.json")
    jsonschema.Draft202012Validator(schema).validate(guide.course_plan)


@pytest.mark.parametrize("mutation, message", [
    (lambda p: p["units"][0]["visual_ids"].append("invented"), "不存在"),
    (lambda p: p["units"][0]["segment_ids"].append("s2"), "未配准"),
    (lambda p: p["units"][0]["anchors"][0].update(quote="模型编造的摘录"), "摘录"),
    (lambda p: p["units"][0]["anchors"].pop(), "每个引用来源"),
    (lambda p: p["units"][2]["dependencies"].append({"unit_id":"load", "reason":"合成循环"}), "循环"),
    (lambda p: p["units"][0]["dependencies"][0].update(unit_id="missing"), "未知"),
    (lambda p: p["units"][0]["dependencies"][0].update(unit_id="load"), "自身"),
    (lambda p: p["units"].pop(), "未知"),
    (lambda p: p["source_dispositions"].append({"ref":"p1","status":"navigation","reason":"跳过"}), "同时"),
])
def test_invalid_plan_is_rejected_then_generation_keeps_all_original_sources(mutation, message):
    plan = proposal()
    mutation(plan)
    with pytest.raises(ValueError, match=message):
        validate_proposal(plan, source_lesson())
    guide = generate_study_guide(source_lesson(), ScriptedPlanner(plan))
    assert guide.report.planning["method"] == "source-headings"
    assert guide.report.status == "draft"
    assert {ref.ref for ref in guide.source_index} == {"p1","p2","p3","p4","p5","p6","s1","s2"}
    assert "另一节课的私有转写" not in " ".join(unit.teacher_increment for unit in guide.units)


def test_omitted_sources_and_misplaced_teacher_segments_fail():
    plan = proposal()
    plan["units"][0]["visual_ids"].remove("p3")
    plan["units"][0]["anchors"] = [anchor for anchor in plan["units"][0]["anchors"] if anchor["ref"] != "p3"]
    with pytest.raises(ValueError, match="遗漏"):
        validate_proposal(plan, source_lesson())
    plan = proposal()
    plan["units"][0]["segment_ids"] = []
    anchor = plan["units"][0]["anchors"].pop()
    plan["units"][1]["segment_ids"] = ["s1"]
    plan["units"][1]["anchors"].append(anchor)
    with pytest.raises(ValueError, match="不匹配"):
        validate_proposal(plan, source_lesson())


def test_offline_grouping_merges_explicit_headings_but_not_generic_examples_or_other_decks():
    lesson = source_lesson()
    lesson.pages.extend([VisualFrame(visual_id="p7", source_id="deck", title="例题", text="第一道题", status="covered"),
                         VisualFrame(visual_id="p8", source_id="deck", title="例题", text="另一个概念的例题", status="covered"),
                         VisualFrame(visual_id="other::p1", source_id="other", title="寄存器", text="另一份材料", status="covered")])
    plan = offline_course(lesson)
    register = next(unit for unit in plan.units if "p2" in unit.visual_ids)
    assert register.visual_ids == ["p2", "p4"]
    assert len([unit for unit in plan.units if unit.title == "例题"]) == 2
    assert all(not unit.prerequisite_ids for unit in plan.units)
    assert plan.method == "source-headings" and plan.status == "draft"


def test_planner_context_limit_does_not_silently_truncate_or_call_provider():
    lesson = source_lesson()
    lesson.pages[0].text = "长材料" * 60_000
    provider = ScriptedPlanner()
    with pytest.raises(ValueError, match="没有向模型发送截断"):
        propose_course(lesson, provider)
    assert provider.planning_calls == 0


def test_existing_maps_use_their_declared_dependencies_and_do_not_request_new_plan():
    lesson = source_lesson()
    lesson.units = [KnowledgeUnit(unit_id="application", title="应用", visual_ids=["p1"], prerequisite_ids=["foundation"]),
                    KnowledgeUnit(unit_id="foundation", title="基础", visual_ids=["p2"])]
    provider = ScriptedPlanner()
    guide = generate_study_guide(lesson, provider)
    assert provider.planning_calls == 0
    assert [unit.unit_id for unit in guide.units] == ["foundation", "application"]
    assert "基础" not in guide.route.prerequisites
    guide.units.reverse()
    assert any(item.code == "dependency.order" for item in validate_study_guide(guide).errors)
    guide.units[0].prerequisite_ids = ["missing"]
    assert any(item.code == "dependency.invalid" for item in validate_study_guide(guide).errors)


def test_unplaced_material_is_visible_as_pending_and_not_taught():
    plan = proposal()
    row = plan["units"].pop(1)
    plan["units"][0]["dependencies"] = plan["units"][0]["dependencies"][:1]
    plan["source_dispositions"] = [{"ref": "p5", "status": "pending", "reason": "缺少图中坐标信息，待视觉复核。"}]
    guide = generate_study_guide(source_lesson(), ScriptedPlanner(plan))
    assert "p5" in guide.report.unresolved_items
    assert next(ref for ref in guide.source_index if ref.ref == "p5").label == "内容待补"
    assert next(ref for ref in guide.source_index if ref.ref == "p5").note == "缺少图中坐标信息，待视觉复核。"
    assert not any("p5" in unit.visual_refs for unit in guide.units)
    for document in (render_html(guide), render_markdown(guide)):
        assert "缺少图中坐标信息，待视觉复核。" in document
    restored = StudyGuide.from_dict(json.loads(guide.to_json()))
    assert next(ref for ref in restored.source_index if ref.ref == "p5").note == "缺少图中坐标信息，待视觉复核。"
    next(ref for ref in guide.source_index if ref.ref == "p5").note = '<script>alert("untrusted source note")</script>'
    for document in (render_html(guide), render_markdown(guide)):
        assert '<script>alert("untrusted source note")</script>' not in document
        assert "&lt;script&gt;" in document


def test_pending_speech_in_provided_unit_is_not_used_without_an_alignment():
    lesson = source_lesson()
    lesson.speech_segments[-1].alignment = None
    lesson.units = [KnowledgeUnit(unit_id="u1", visual_ids=["p1"], segment_ids=["s2"])]
    guide = generate_study_guide(lesson)
    assert "另一节课的私有转写" not in guide.units[0].teacher_increment


def test_many_source_topics_are_not_presented_as_a_reconstructed_mainline():
    lesson = LessonMap(pages=[VisualFrame(visual_id=f"deck::p{i}", source_id="deck", page=i,
                       title=f"原文主题{i}", text=f"原文材料{i}", status="covered") for i in range(1, 10)])
    guide = generate_study_guide(lesson)
    assert len(guide.units) == 9
    assert guide.route.chain == []
    assert any("精简学习主线" in warning for warning in guide.report.warnings)
    for document in (render_html(guide), render_markdown(guide)):
        assert "学习主线待梳理" in document
    assert len({ref.ref for ref in guide.source_index}) == 9


@pytest.mark.parametrize("status", ["navigation", "context"])
def test_planner_cannot_hide_uncertain_speech_as_low_value_material(status):
    plan = proposal()
    plan["source_dispositions"] = [{"ref": "s2", "status": status, "reason": "模型认为可以忽略。"}]
    with pytest.raises(ValueError, match="必须保留待确认"):
        validate_proposal(plan, source_lesson())


def test_regeneration_with_supplied_units_clears_a_stale_course_plan(tmp_path):
    paths = project_paths(tmp_path)
    lesson = source_lesson()
    write_json(paths["lesson_map"], lesson.to_dict())
    generate_project_guide(tmp_path)
    assert read_json(paths["derived"] / "course-plan.json") is not None
    lesson.units = [KnowledgeUnit(unit_id="manual", title="人工整理单元", visual_ids=["p1"])]
    write_json(paths["lesson_map"], lesson.to_dict())
    guide = generate_project_guide(tmp_path)
    assert guide.course_plan is None
    assert read_json(paths["derived"] / "course-plan.json") is None
    assert guide.report.planning["method"] == "provided-units"
