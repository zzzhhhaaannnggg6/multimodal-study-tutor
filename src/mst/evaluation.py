"""Local numerical teaching benchmark with independent answer interpretation.

This checks a bounded synthetic task bank, not general teaching correctness.
The reference reader does not import the generator's numeral parser/solver.
"""

from __future__ import annotations

import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from .answer_checks import BASES as _BASES, LITERAL as _LITERAL, answer_values as _answer_values, reference_value
from .guide import StudyGuide, generate_study_guide
from .models import KnowledgeUnit, LessonMap, VisualFrame


def load_suite(value: dict[str, Any] | str | Path) -> dict[str, Any]:
    suite = json.loads(Path(value).read_text(encoding="utf-8")) if isinstance(value, (str, Path)) else value
    if not isinstance(suite, dict) or suite.get("suite_version") != "1.0" or not isinstance(suite.get("suite_id"), str):
        raise ValueError("Evaluation suite needs a version and ID.")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000:
        raise ValueError("Evaluation suite needs 1–1000 cases.")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", case["case_id"]):
            raise ValueError("Evaluation case ID is invalid.")
        if case["case_id"] in seen:
            raise ValueError("Evaluation case IDs must be unique.")
        seen.add(case["case_id"])
        if case.get("mode") not in {"solve", "conflict", "abstain"} or not isinstance(case.get("source_text"), str) or not case["source_text"].strip():
            raise ValueError("Evaluation case needs source text and a supported expectation.")
        if case.get("forbidden") is not None and (not isinstance(case["forbidden"], list) or any(not isinstance(item, str) for item in case["forbidden"])):
            raise ValueError("Forbidden output fragments must be strings.")
        if case["mode"] != "abstain":
            source = reference_value(case["source"], case["source_base"])
            target = reference_value(case["target"], case["target_base"])
            if source != target:
                raise ValueError("Golden source and target disagree; fix the evaluation case.")
            if case["mode"] == "solve" and Fraction(case["delta"]) <= 0:
                raise ValueError("Transfer change must be positive.")
            if case["mode"] == "conflict" and source == reference_value(case["supplied_answer"], case["target_base"]):
                raise ValueError("A conflict case must contain a conflicting source answer.")
    return suite


def case_map(case: dict[str, Any]) -> LessonMap:
    ref = f"eval::{case['case_id']}::p001"
    return LessonMap(lesson_id=f"eval::{case['case_id']}", title="合成数制评测", subject="computer-systems", profile="computer-systems",
                     pages=[VisualFrame(visual_id=ref, page=1, title="进制转换", text=case["source_text"], status="covered")],
                     units=[KnowledgeUnit(unit_id=f"eval::{case['case_id']}::unit", title="进制转换", visual_ids=[ref], understanding_level="U2")])


def evaluate_case(case: dict[str, Any], guide: StudyGuide) -> dict[str, Any]:
    failures = []
    ref = f"eval::{case['case_id']}::p001"
    if guide.lesson_id != f"eval::{case['case_id']}":
        failures.append("candidate.lesson_identity")
    refs = [item for item in guide.source_index if item.ref == ref]
    if len(refs) != 1 or refs[0].quote != case["source_text"]:
        failures.append("source.original_preserved")
    unit_refs = [item for unit in guide.units for item in unit.source_refs]
    if not unit_refs or any(item.ref != ref or item.quote != case["source_text"] for item in unit_refs):
        failures.append("source.unit_evidence_changed")
    examples = [item for unit in guide.units for item in unit.worked_examples]
    if not examples:
        failures.append("example.missing")
    elif len(examples) != 1:
        failures.append("example.ambiguous_case")
    text = "\n".join(item.question + item.setup + "".join(item.steps) + item.answer + item.variation for item in examples)
    for fragment in case.get("forbidden", []):
        if fragment in text:
            failures.append("source.invented_problem")
    if case["mode"] == "abstain":
        if any(item.complete for item in examples):
            failures.append("unsupported.claims_complete")
    elif examples:
        example = examples[0]
        expected = reference_value(case["target"], case["target_base"])
        values = _answer_values(example.answer, case["target_base"])
        question_literals = [(row["digits"].upper(), _BASES[row["base"]]) for row in _LITERAL.finditer(example.question)]
        if question_literals != [(case["source"].upper(), case["source_base"])]:
            failures.append("source.problem_changed")
        if case["mode"] == "conflict":
            supplied = reference_value(case["supplied_answer"], case["target_base"])
            if example.complete or "【待确认】" not in example.answer or expected not in values or supplied not in values:
                failures.append("source.conflict_not_preserved")
            if ref not in guide.report.unresolved_items or guide.report.status == "complete":
                failures.append("source.conflict_not_pending")
        else:
            if not example.complete:
                failures.append("example.not_complete")
            if values != [expected]:
                failures.append("answer.incorrect_or_ambiguous")
            if len(example.steps) < 3 or not example.variation.strip():
                failures.append("example.process_missing")
            practices = [item for unit in guide.units for item in unit.practice_items]
            retrieval = [item for item in practices if item.kind == "retrieval"]
            weight = re.search(r"1/(\d+)", retrieval[0].answer) if len(retrieval) == 1 else None
            if weight is None or int(weight[1]) != case["source_base"]:
                failures.append("retrieval.answer_incorrect")
            transfer = [item for item in practices if item.kind == "transfer"]
            if len(transfer) != 1 or _answer_values(transfer[0].answer, case["target_base"]) != [expected + Fraction(case["delta"])]:
                failures.append("transfer.incorrect")
            process = [item for item in practices if item.kind == "process"]
            decimal = re.search(r"十进制\s+([+-]?\d+(?:\.\d+)?)", process[0].answer) if len(process) == 1 else None
            if decimal is None or Fraction(decimal[1]) != expected:
                failures.append("process.answer_incorrect")
    return {"case_id": case["case_id"], "mode": case["mode"], "passed": not failures, "failures": failures,
            "guide_fingerprint": hashlib.sha256(guide.to_json().encode()).hexdigest()}


def evaluate_suite(value: dict[str, Any] | str | Path, *, guides_dir: str | Path | None = None, save_guides: str | Path | None = None) -> dict[str, Any]:
    suite = load_suite(value)
    results = []
    for case in suite["cases"]:
        try:
            guide = StudyGuide.from_json(Path(guides_dir) / f"{case['case_id']}.json") if guides_dir is not None else generate_study_guide(case_map(case))
            if save_guides is not None:
                guide.write_json(Path(save_guides) / f"{case['case_id']}.json")
            results.append(evaluate_case(case, guide))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
            results.append({"case_id": case["case_id"], "mode": case["mode"], "passed": False, "failures": ["candidate.unreadable_or_invalid"]})
    passed = sum(result["passed"] for result in results)
    return {"report_version": "1.0", "suite_id": suite["suite_id"],
            "suite_fingerprint": hashlib.sha256(json.dumps(suite, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "candidate": "precomputed-guides" if guides_dir is not None else "offline-generator",
            "scope": "Synthetic numerical results, transfer answers and source boundaries only. Not expert review, student testing or general teaching verification.",
            "total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
