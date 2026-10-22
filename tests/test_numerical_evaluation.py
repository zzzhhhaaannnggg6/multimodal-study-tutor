"""Numerical expectations use a separate positional/geometric-series reader."""

from __future__ import annotations

import copy
import json
from fractions import Fraction
from pathlib import Path

import pytest

from mst.cli import main
from mst.evaluation import case_map, evaluate_case, evaluate_suite, load_suite, reference_value
from mst.guide import StudyGuide, generate_study_guide, render_html, render_markdown, validate_study_guide
from mst.io import read_json, write_json
from mst.numerals import expand, number_example, parse_number
from mst.models import LessonMap, VisualFrame


SUITE_PATH = Path(__file__).parents[1] / "evals" / "number-conversion-v1.json"
SUITE = load_suite(SUITE_PATH)
NOTATION_PATH = SUITE_PATH.with_name("number-notation-v1.json")
NOTATION_SUITE = load_suite(NOTATION_PATH)


@pytest.mark.parametrize("case", [*SUITE["cases"], *NOTATION_SUITE["cases"]], ids=lambda case: case["case_id"])
def test_public_synthetic_bank_checks_actual_generated_answers(case):
    guide = generate_study_guide(case_map(case))
    result = evaluate_case(case, guide)
    assert result["passed"], result["failures"]
    assert StudyGuide.from_dict(guide.to_dict()).to_dict() == guide.to_dict()
    if case["mode"] == "solve":
        assert case["source"] in guide.units[0].one_sentence
        assert "PC" not in guide.units[0].one_sentence + "".join(guide.units[0].step_chain)
        assert case["source"] in guide.units[0].question
        for prerequisite in guide.units[0].prerequisites:
            assert prerequisite in render_html(guide)


@pytest.mark.parametrize("base", [2, 8, 10, 16])
def test_sign_integer_fraction_and_recurrence_preserve_exact_values(base):
    # Independent reference uses positional weights and a geometric series;
    # the producer uses remainder cycles. Include values across zero and carries.
    for numerator in range(-40, 41):
        for denominator in (1, 2, 5, 8, 16, 25):
            value = Fraction(numerator, denominator)
            result = expand(value, base)
            assert reference_value(result.digits, base) == value


@pytest.mark.parametrize("mutation, code", [
    (lambda guide: setattr(guide.units[0].worked_examples[0], "answer", "【导师补链】(635.12)₈ = (19D.3F8)₁₆。"), "answer.incorrect_or_ambiguous"),
    (lambda guide: setattr(guide.units[0].worked_examples[0], "question", "把 (635.177)₈ 换成十六进制。"), "source.problem_changed"),
    (lambda guide: setattr(guide.units[0].practice_items[2], "answer", "(19D.28)₁₆"), "transfer.incorrect"),
    (lambda guide: setattr(guide.units[0].practice_items[1], "answer", "十进制 413.25。"), "process.answer_incorrect"),
    (lambda guide: setattr(guide.units[0].practice_items[0], "answer", "位权为 1/16。"), "retrieval.answer_incorrect"),
    (lambda guide: setattr(guide.source_index[0], "quote", "另一个问题"), "source.original_preserved"),
    (lambda guide: setattr(guide, "lesson_id", "wrong-lesson"), "candidate.lesson_identity"),
])
def test_wrong_answers_fail_even_when_all_teaching_fields_are_present(mutation, code):
    case = next(case for case in SUITE["cases"] if case["case_id"] == "octal-changed-fraction")
    guide = generate_study_guide(case_map(case))
    mutation(guide)
    guide.report.status = "complete"
    guide.units[0].status = "ready"
    guide.units[0].worked_examples[0].complete = True
    assert code in evaluate_case(case, guide)["failures"]


def test_material_conflict_is_preserved_in_exports_and_pending_sources():
    case = next(case for case in SUITE["cases"] if case["case_id"] == "conflicting-binary-answer")
    lesson = case_map(case)
    original = copy.deepcopy(lesson.to_dict())
    guide = generate_study_guide(lesson)
    ref = guide.source_index[0]
    assert ref.label == "材料计算待核对"
    assert not ref.verified and ref.status == "pending"
    assert ref.quote == case["source_text"]
    assert lesson.to_dict() == original
    for document in (render_html(guide), render_markdown(guide)):
        assert "5.25" in document and "5.5" in document and "待确认" in document
    # Silently promoting the conflict to complete must fail evaluation.
    guide.units[0].worked_examples[0].complete = True
    assert "source.conflict_not_preserved" in evaluate_case(case, guide)["failures"]


def test_exact_fraction_solver_does_not_introduce_floating_rounding():
    assert parse_number("9007199254740993", 10) == Fraction(9007199254740993)
    assert expand(Fraction(1, 10), 2).digits == "0.0(0011)"
    assert number_example("Decimal to binary: 0.0001") is None
    with pytest.raises(ValueError, match="截断"):
        expand(Fraction(1, 10_000), 2)


def test_local_cli_report_candidates_and_missing_candidate_failure(tmp_path, capsys):
    candidates = tmp_path / "candidates"
    report_path = tmp_path / "report.json"
    assert main(["evaluate", str(SUITE_PATH), "--save-guides", str(candidates), "--output", str(report_path)]) == 0
    report = read_json(report_path)
    assert report["total"] == len(SUITE["cases"]) and report["failed"] == 0
    assert "Not expert review" in report["scope"]
    assert "synthetic cases passed" in capsys.readouterr().out
    assert main(["evaluate", str(SUITE_PATH), "--guides-dir", str(candidates)]) == 0
    guide_path = candidates / "octal-changed-fraction.json"
    guide = StudyGuide.from_json(guide_path)
    guide.units[0].worked_examples[0].answer = "(19D.3F8)₁₆"
    guide.write_json(guide_path)
    assert main(["evaluate", str(SUITE_PATH), "--guides-dir", str(candidates), "--output", str(report_path)]) == 1
    assert read_json(report_path)["failed"] == 1
    missing = evaluate_suite(SUITE, guides_dir=tmp_path / "missing")
    assert missing["failed"] == missing["total"]


def test_invalid_benchmark_cannot_make_a_false_success_report(tmp_path):
    for mutate in (
        lambda suite: suite["cases"][0].update(target="FFFF"),
        lambda suite: suite["cases"][0].update(case_id="../outside"),
        lambda suite: suite["cases"].append(copy.deepcopy(suite["cases"][0])),
    ):
        invalid = copy.deepcopy(SUITE)
        mutate(invalid)
        with pytest.raises(ValueError):
            load_suite(invalid)
        path = write_json(tmp_path / "invalid.json", invalid)
        assert main(["evaluate", str(path)]) == 2


class ExistingNumericProvider:
    name = "synthetic-existing-numeric"

    def __init__(self, answer=None):
        self.answer = answer

    def complete(self, **kwargs):
        prompt = json.loads(kwargs["user"])
        assert "numerical_contract" in prompt
        data = prompt["existing"]
        if self.answer is not None:
            data["worked_examples"][0]["answer"] = self.answer
            data["worked_examples"][0]["complete"] = True
        return json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize("answer", ["(19D.3F8)₁₆", "答案大约是 413，省略其余过程。"])
def test_provider_wrong_or_unreadable_numeric_answer_stays_a_draft(answer):
    case = next(case for case in SUITE["cases"] if case["case_id"] == "octal-changed-fraction")
    lesson = case_map(case)
    accepted = generate_study_guide(lesson, ExistingNumericProvider())
    assert accepted.report.status == "complete"
    assert validate_study_guide(accepted, strict=True).ok
    guide = generate_study_guide(lesson, ExistingNumericProvider(answer))
    assert guide.report.status == "draft"
    assert any(field.endswith("numeric_answer_unverified") for field in guide.report.missing_fields)
    assert any("精确数值核对" in warning for warning in guide.report.warnings)
    assert not validate_study_guide(guide, strict=True).ok
    # A saved guide's status alone cannot bypass the same strict check.
    guide.report.status = "complete"
    assert not validate_study_guide(guide, strict=True).ok


def test_provider_cannot_erase_a_known_material_calculation_conflict():
    case = next(case for case in SUITE["cases"] if case["case_id"] == "conflicting-binary-answer")
    guide = generate_study_guide(case_map(case), ExistingNumericProvider("一切正确，无需核对。"))
    assert guide.report.status == "draft"
    assert not guide.units[0].worked_examples[0].complete
    assert "5.25" in guide.units[0].worked_examples[0].answer
    assert "5.5" in guide.units[0].worked_examples[0].answer
    assert "【待确认】" in guide.units[0].worked_examples[0].answer


@pytest.mark.parametrize("kind, wrong", [("process", "十进制 413.25。"), ("transfer", "(19D.28)₁₆")])
def test_provider_practice_arithmetic_is_checked_before_completing_a_guide(kind, wrong):
    class WrongPractice(ExistingNumericProvider):
        def complete(self, **kwargs):
            data = json.loads(super().complete(**kwargs))
            next(item for item in data["practice_items"] if item["kind"] == kind)["answer"] = wrong
            return json.dumps(data, ensure_ascii=False)

    case = next(case for case in SUITE["cases"] if case["case_id"] == "octal-changed-fraction")
    guide = generate_study_guide(case_map(case), WrongPractice())
    assert guide.report.status == "draft"
    assert any(field.endswith(f"numeric_{kind}_unverified") for field in guide.report.missing_fields)
    assert not validate_study_guide(guide, strict=True).ok


@pytest.mark.parametrize("text", ["multiple bit binary addition 01100 10001 two's complement", "minuend 10110 10010 有符号补码"])
def test_signed_binary_material_does_not_get_an_unsigned_decimal_story(text):
    guide = generate_study_guide(LessonMap(profile="computer-systems", pages=[VisualFrame(visual_id="p1", title="补码运算", text=text, status="covered")]))
    assert not guide.units[0].worked_examples[0].complete
    assert "12+17=29" not in " ".join(guide.units[0].worked_examples[0].steps)


@pytest.mark.parametrize("source", ["将二进制100101.01转换成十进制", "把(100101.01)₂转成十进制", "把(100101.01)b转换为十进制"])
def test_chinese_text_does_not_require_spaces_around_numbers(source):
    result = number_example(source)
    assert result and result["complete"]
    assert "(37.25)₁₀" in result["answer"]


def test_conflicting_conversion_directions_remain_unresolved():
    assert number_example("Octal to hexadecimal: (635)O = (413)D") is None


@pytest.mark.parametrize("profile", ["generic", "mathematics", "physics", "computer-systems"])
def test_exact_positional_explanation_is_available_across_subjects(profile):
    source = "将二进制 (1101)2 转换为十进制，按位权展开计算。"
    lesson = LessonMap(subject=profile, profile=profile, pages=[VisualFrame(visual_id="p1", title="数的表示", text=source, status="covered")])
    guide = generate_study_guide(lesson)
    unit = guide.units[0]
    assert unit.worked_examples[0].complete
    assert "(13)₁₀" in unit.worked_examples[0].answer
    assert "(14)₁₀" in next(item.answer for item in unit.practice_items if item.kind == "transfer")
    assert "PC" not in unit.tutor_bridge + "".join(unit.step_chain)
    assert unit.source_refs[0].quote == source
    assert guide.report.status == "draft"  # The course has not been reviewed.


@pytest.mark.parametrize("case_id", ["mathematical-minus", "negative-binary-prefix", "minus-outside-parentheses"])
def test_provider_cannot_promote_a_lost_negative_sign_to_a_complete_answer(case_id):
    case = next(item for item in NOTATION_SUITE["cases"] if item["case_id"] == case_id)
    wrong_positive = f"({case['target'].lstrip('-')})₁₀"
    guide = generate_study_guide(case_map(case), ExistingNumericProvider(wrong_positive))
    assert guide.report.status == "draft"
    assert any(field.endswith("numeric_answer_unverified") for field in guide.report.missing_fields)
    assert not validate_study_guide(guide, strict=True).ok


@pytest.mark.parametrize("level", ["guide", "unit"])
def test_unsupported_case_cannot_pass_evaluation_by_claiming_ready_without_a_complete_example(level):
    case = next(item for item in NOTATION_SUITE["cases"] if item["case_id"] == "identical-operands-are-an-expression")
    guide = generate_study_guide(case_map(case))
    assert not guide.units[0].worked_examples[0].complete
    if level == "guide":
        guide.report.status = "complete"
    else:
        guide.units[0].status = "ready"
    assert "unsupported.claims_complete" in evaluate_case(case, guide)["failures"]


@pytest.mark.parametrize("expression", [
    "(101)B + x", "x + (101)B", "(101)B - x", "x - (101)B",
    "(101)B × x", "x * (101)B", "sqrt((101)B)", "((101)B)²", "-((101)B)",
])
def test_unsupported_operations_cannot_be_dropped_around_a_marked_operand(expression):
    assert number_example("Binary to decimal: " + expression) is None
