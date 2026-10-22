"""Check explicit binary results and column work with prefix arithmetic.

The producer uses a carry/borrow recurrence. This checker instead compares
low-bit prefixes of whole integers. It cannot certify arbitrary prose.
"""

from __future__ import annotations

import re
from typing import Any

from .answer_checks import LITERAL, answer_values
from .binary_arithmetic import binary_example, find_binary_problem
from .teaching import normalized


_COLUMN = re.compile(
    r"第\s*(\d+)\s*位（位权\s*2\^(\d+)）：\s*([01])\s*([+-])\s*([01])\s*([+-])\s*(进位|借位)\s*([01])\s*=\s*(-?\d+)；"
    r"本位写\s*([01])，向左(进位|借位)\s*([01])。")


def reference_columns(left: str, right: str, operator: str) -> list[tuple[int, ...]]:
    a, b = int(left, 2), int(right, 2)
    columns = []
    for index in range(max(len(left), len(right))):
        lower_mask = (1 << index) - 1
        prefix_mask = (1 << (index + 1)) - 1
        ai, bi = (a >> index) & 1, (b >> index) & 1
        incoming = ((a & lower_mask) + (b & lower_mask)) >> index if operator == "+" else int((a & lower_mask) < (b & lower_mask))
        total = ai + bi + incoming if operator == "+" else ai - bi - incoming
        result = a + b if operator == "+" else a - b
        outgoing = ((a & prefix_mask) + (b & prefix_mask)) >> (index + 1) if operator == "+" else int((a & prefix_mask) < (b & prefix_mask))
        columns.append((index, ai, bi, incoming, total, (result >> index) & 1, outgoing))
    return columns


def read_columns(steps: list[str], operator: str) -> list[tuple[int, ...]]:
    rows = []
    name = "进位" if operator == "+" else "借位"
    for match in _COLUMN.finditer("\n".join(steps)):
        if match[1] != match[2] or match[4] != operator or match[6] != operator or match[7] != name or match[11] != name:
            return []
        try:
            rows.append(tuple(int(match[index]) for index in (1, 3, 5, 8, 9, 10, 12)))
        except ValueError:
            return []
    return rows


def binary_values(text: str) -> list:
    try:
        return answer_values(text, 2)
    except ValueError:
        return []  # Unreadable is pending, never a successful answer.


def question_matches(question: str, left: str, right: str, operator: str) -> bool:
    matches = list(LITERAL.finditer(question))
    return ([(m["digits"], m["base"]) for m in matches] == [(left, "₂"), (right, "₂")]
            and question[matches[0].end():matches[1].start()].strip() == operator)


def binary_issues(unit: Any) -> list[str]:
    source = "\n".join(ref.quote or "" for ref in unit.source_refs if ref.kind == "material")
    problem = find_binary_problem(source)
    if problem is None:
        return []
    a, b = int(problem.left, 2), int(problem.right, 2)
    value = a + b if problem.operator == "+" else a - b
    expected = reference_columns(problem.left, problem.right, problem.operator)
    derived = binary_example(source)
    issues = []
    if unit.worked_examples and unit.worked_examples[0].complete:
        example = unit.worked_examples[0]
        if not question_matches(example.question, problem.left, problem.right, problem.operator):
            issues.append("worked_examples.binary_source_unverified")
        if binary_values(example.answer) != [value]:
            issues.append("worked_examples.binary_answer_unverified")
        if read_columns(example.steps, problem.operator) != expected:
            issues.append("worked_examples.binary_columns_unverified")
        variant = list(LITERAL.finditer(example.variation))
        if (len(variant) != 3 or [m["digits"] for m in variant[:2]] != [format(a + 1, "b").zfill(len(problem.left)), problem.right]
                or any(m["base"] != "₂" for m in variant) or binary_values(variant[-1][0]) != [value + 1]
                or example.variation[variant[0].end():variant[1].start()].strip() != problem.operator):
            issues.append("worked_examples.binary_variation_unverified")
    for kind in ("retrieval", "process", "transfer"):
        items = [item for item in unit.practice_items if item.kind == kind]
        fixed = next(item for item in derived["practice"] if item["kind"] == kind)
        if len(items) != 1 or normalized(items[0].prompt) != normalized(fixed["prompt"]):
            issues.append(f"practice_items.binary_{kind}_conditions_unverified")
        if len(items) != 1:
            continue
        item = items[0]
        if kind == "retrieval":
            valid = normalized(item.answer) == normalized(fixed["answer"])
        elif kind == "transfer":
            valid = binary_values(item.answer) == [value + 1]
            if read_columns([item.explanation], problem.operator) != reference_columns(format(a + 1, "b").zfill(len(problem.left)), problem.right, problem.operator):
                issues.append("practice_items.binary_transfer_process_unverified")
        else:
            chosen = next((c for c in expected if c[-1] and c[3]), next((c for c in expected if c[-1]), expected[0]))
            carry = "进位" if problem.operator == "+" else "借位"
            valid = (re.findall(r"本位\s*=\s*([01])", item.answer) == [str(chosen[-2])]
                     and re.findall(carry + r"\s*=\s*([01])", item.answer) == [str(chosen[-1])])
            if read_columns([item.explanation], problem.operator) != [chosen]:
                issues.append("practice_items.binary_process_explanation_unverified")
        if not valid:
            issues.append(f"practice_items.binary_{kind}_answer_unverified")
    return issues


__all__ = ["binary_issues", "reference_columns", "read_columns", "question_matches", "binary_values"]
