"""Fixed gold, independent prefix arithmetic, and deliberately wrong lessons."""

import base64
import copy
import json
from pathlib import Path

import pytest

from mst.binary_arithmetic import BinaryProblem, binary_columns, binary_example
from mst.binary_checks import binary_values, read_columns, reference_columns
from mst.cli import main
from mst.evaluation import case_map, evaluate_case, evaluate_suite, load_suite
from mst.guide import StudyGuide, generate_study_guide, render_html, render_markdown, validate_study_guide
from mst.io import read_json
from mst.jobs import JobManager
from mst.models import LessonMap, VisualFrame
from pdf_fixtures import visual_pdf
from test_numerical_inputs import slide_bytes


SUITE_PATH = Path(__file__).parents[1] / "evals/binary-arithmetic-v1.json"
SUITE = load_suite(SUITE_PATH)


@pytest.mark.parametrize("case", SUITE["cases"], ids=lambda case: case["case_id"])
def test_fixed_binary_bank_checks_actual_lectures_and_source_boundaries(case):
    lesson = case_map(case)
    original = lesson.to_dict()
    guide = generate_study_guide(lesson)
    result = evaluate_case(case, guide)
    assert result["passed"], result["failures"]
    assert lesson.to_dict() == original
    assert StudyGuide.from_dict(guide.to_dict()).to_dict() == guide.to_dict()
    unit = guide.units[0]
    assert guide.report.status == "draft"  # Offline calculation isn't expert review.
    if case["mode"] == "solve":
        assert unit.content_mode == "lesson"
        assert not guide.report.missing_fields
        assert len(unit.practice_items) == 3
        for text in (render_html(guide), render_markdown(guide)):
            assert "本位写" in text and "展开答案与解析" in text
            assert "先定位被改变的条件" not in text
    elif case["mode"] == "abstain":
        assert unit.content_mode == "material-only"
        assert not unit.practice_items and not unit.worked_examples


def test_five_bit_columns_match_whole_integer_and_prefix_reference():
    for a in range(32):
        for b in range(32):
            for op in ("+", "-"):
                if op == "-" and a < b:
                    continue
                left, right = format(a, "05b"), format(b, "05b")
                result, columns = binary_columns(BinaryProblem(left, right, op))
                assert int(result, 2) == (a + b if op == "+" else a - b)
                actual = [tuple(c[key] for key in ("index", "a", "b", "incoming", "total", "bit", "outgoing")) for c in columns]
                assert actual == reference_columns(left, right, op)


class EchoArithmetic:
    name = "synthetic-arithmetic"

    def complete(self, **kwargs):
        prompt = json.loads(kwargs["user"])
        assert "binary_arithmetic_contract" in prompt
        data = prompt["existing"]
        self.mutate(data)
        return json.dumps(data, ensure_ascii=False)

    def mutate(self, data):
        pass


def carry_case():
    return next(case for case in SUITE["cases"] if case["case_id"] == "addition-carry-chain")


@pytest.mark.parametrize("mutation, code", [
    (lambda d: d["worked_examples"][0].update(answer="(01001)₂"), "worked_examples.binary_answer_unverified"),
    (lambda d: d["worked_examples"][0].update(answer="(102)₂"), "worked_examples.binary_answer_unverified"),
    (lambda d: d["worked_examples"][0].update(question=d["worked_examples"][0]["question"].replace(" + ", " - ")), "worked_examples.binary_source_unverified"),
    (lambda d: d["worked_examples"][0]["steps"].__setitem__(1, d["worked_examples"][0]["steps"][1].replace("= 2；", "= 3；")), "worked_examples.binary_columns_unverified"),
    (lambda d: d["worked_examples"][0]["steps"].pop(2), "worked_examples.binary_columns_unverified"),
    (lambda d: d["worked_examples"][0].update(variation=d["worked_examples"][0]["variation"].replace("完整结果为 (01001)₂", "完整结果为 (01000)₂")), "worked_examples.binary_variation_unverified"),
    (lambda d: d["practice_items"][0].update(answer="本位=1；进位=0。"), "practice_items.binary_retrieval_answer_unverified"),
    (lambda d: d["practice_items"][1].update(answer="本位=1；进位=1。"), "practice_items.binary_process_answer_unverified"),
    (lambda d: d["practice_items"][1].update(explanation=d["practice_items"][1]["explanation"].replace("= 2；", "= 0；")), "practice_items.binary_process_explanation_unverified"),
    (lambda d: d["practice_items"][2].update(answer="(01000)₂"), "practice_items.binary_transfer_answer_unverified"),
    (lambda d: d["practice_items"][2].update(prompt=d["practice_items"][2]["prompt"].replace(" + ", " - ")), "practice_items.binary_transfer_conditions_unverified"),
    (lambda d: d["practice_items"][2].update(explanation=d["practice_items"][2]["explanation"].replace("= 1；", "= 0；")), "practice_items.binary_transfer_process_unverified"),
])
def test_wrong_model_conditions_results_or_column_work_stay_draft(mutation, code):
    class Wrong(EchoArithmetic):
        def mutate(self, data):
            mutation(data)
    guide = generate_study_guide(case_map(carry_case()), Wrong())
    assert guide.report.status == "draft"
    assert any(field.endswith(code) for field in guide.report.missing_fields), guide.report.missing_fields
    assert any("二进制运算" in text for text in guide.report.warnings)
    assert not validate_study_guide(guide, strict=True).ok
    guide.report.status = "complete"
    assert not validate_study_guide(guide, strict=True).ok  # Saved flags don't bypass checking.


@pytest.mark.parametrize("case_id", ["addition-carry-chain", "subtraction-borrow-chain"])
def test_synthetic_echo_can_pass_existing_checks_without_claiming_expert_review(case_id):
    case = next(case for case in SUITE["cases"] if case["case_id"] == case_id)
    guide = generate_study_guide(case_map(case), EchoArithmetic())
    assert guide.report.status == "complete"
    assert validate_study_guide(guide, strict=True).ok
    assert evaluate_case(case, guide)["passed"]


def test_a_model_cannot_erase_a_known_arithmetic_source_conflict():
    class Erase(EchoArithmetic):
        def mutate(self, data):
            data["worked_examples"][0].update(answer="(1000)₂", complete=True)
            data["material_explanation"] = "材料答案正确，不存在任何冲突。"
    case = next(case for case in SUITE["cases"] if case["case_id"] == "addition-source-conflict")
    guide = generate_study_guide(case_map(case), Erase())
    assert evaluate_case(case, guide)["passed"]
    assert not guide.units[0].worked_examples[0].complete
    for text in (render_html(guide), render_markdown(guide)):
        assert "待确认" in text and "(1000)₂" in text and "(111)₂" in text
        assert "不存在任何冲突" not in text


@pytest.mark.parametrize("profile", ["computer-systems", "mathematics", "generic"])
def test_binary_arithmetic_has_the_same_explicit_meaning_across_subjects(profile):
    lesson = LessonMap(profile=profile, pages=[VisualFrame(visual_id="p1", text="二进制减法：10000-00001", status="covered")])
    guide = generate_study_guide(lesson)
    assert binary_values(guide.units[0].worked_examples[0].answer) == [15]
    assert not guide.report.missing_fields


def test_other_recognized_topics_do_not_receive_generic_fake_exercises():
    source = "Instruction Fetch, Instruction Decode, Execute, Memory Access, Write Back"
    guide = generate_study_guide(LessonMap(profile="computer-systems", pages=[VisualFrame(visual_id="p1", text=source, status="covered")]))
    assert guide.units[0].worked_examples  # Keep the existing stage explanation.
    assert not guide.units[0].practice_items and not guide.review_items
    assert any(field.endswith("practice_items>=3") for field in guide.report.missing_fields)
    for text in (render_html(guide), render_markdown(guide)):
        assert "先定位被改变的条件" not in text
        assert "请按正确顺序写出完成这个知识点" not in text


@pytest.mark.parametrize("format, source, expected, changed", [
    ("md", "二进制加法：00111+00001", 8, 9),
    ("pptx", "二进制减法：１００００−００００１", 15, 16),
    ("pdf", "Binary addition: 1111+0001", 16, 17),
])
def test_real_import_formats_reach_concrete_column_work_and_source_preserving_exports(tmp_path, format, source, expected, changed):
    if format == "pdf":
        pytest.importorskip("pypdf")
        pytest.importorskip("pypdfium2")
        content = visual_pdf(1, page_text=source)
    elif format == "pptx":
        content = slide_bytes(source)
    else:
        content = ("# 二进制运算\n" + source).encode()
    manager = JobManager(tmp_path)
    try:
        job = manager.submit([{"name": "合成算术." + format, "data": base64.b64encode(content).decode()}], subject="computer-systems")
        assert manager.events[job["job_id"]].wait(20)
        assert manager.get(job["job_id"])["status"] == "succeeded"
        root = manager.active_root()
        guide = StudyGuide.from_json(root / "derived/study-guide.json")
        unit = guide.units[0]
        assert binary_values(unit.worked_examples[0].answer) == [expected]
        transfer = next(p for p in unit.practice_items if p.kind == "transfer")
        assert binary_values(transfer.answer) == [changed]
        assert len(read_columns(unit.worked_examples[0].steps, "+" if format != "pptx" else "-")) >= 4
        assert any(source in ref.quote for ref in unit.source_refs)
        assert next((root / "sources").rglob("*." + format)).read_bytes() == content
        assert "本位写" in (root / "exports/study-guide.html").read_text()
    finally:
        manager.close()


@pytest.mark.parametrize("mutation, code", [
    (lambda g: setattr(g.units[0].worked_examples[0], "answer", "(01001)₂"), "answer.incorrect_or_incomplete"),
    (lambda g: g.units[0].worked_examples[0].steps.pop(1), "example.columns_incorrect"),
    (lambda g: setattr(g.units[0].practice_items[2], "answer", "(01000)₂"), "transfer.incorrect"),
    (lambda g: setattr(g.units[0].practice_items[1], "explanation", "第 0 位算成错误结果。"), "process.explanation_incorrect"),
])
def test_fixed_gold_evaluation_fails_despite_complete_fields(mutation, code):
    case = carry_case()
    guide = generate_study_guide(case_map(case))
    mutation(guide)
    assert code in evaluate_case(case, guide)["failures"]


def test_arithmetic_cli_and_invalid_gold_bank_cannot_report_false_success(tmp_path):
    candidates = tmp_path / "candidates"
    report = tmp_path / "report.json"
    assert main(["evaluate", str(SUITE_PATH), "--save-guides", str(candidates), "--output", str(report)]) == 0
    assert read_json(report)["total"] == 41
    assert main(["evaluate", str(SUITE_PATH), "--guides-dir", str(candidates)]) == 0
    missing = evaluate_suite(SUITE, guides_dir=tmp_path / "missing")
    assert missing["failed"] == 41
    invalid = copy.deepcopy(SUITE)
    invalid["cases"][0]["result"] = "11100"
    with pytest.raises(ValueError, match="Golden arithmetic"):
        load_suite(invalid)
