"""Observable teaching failures; these checks do not certify factual truth."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def normalized(text: Any) -> str:
    value = re.sub(r"【[^】]*】", "", str(text or ""))
    # Math and code punctuation (and letter case) can change a claim's meaning:
    # x+1 != x-1, x=1 != x!=1, and x is not necessarily X.
    value = re.sub(r"\s+", "", value)
    return value.translate(str.maketrans("", "", "，。；：？“”‘’、")).strip(".,;:?")


def specific_steps(steps: list[str]) -> bool:
    values = [normalized(step) for step in steps]
    generic = {normalized(text) for text in ("检查条件", "完成过程", "核对结果", "根据公式计算", "套用公式", "完成计算", "得出结果", "分析问题", "写出答案")}
    return len(set(values) - generic - {""}) >= 3


def teaching_issues(unit: Any) -> list[str]:
    issues = []
    if unit.step_chain and len({normalized(step) for step in unit.step_chain}) < len(unit.step_chain):
        issues.append("step_chain.repeated")
    if unit.material_explanation and normalized(unit.material_explanation) == normalized(unit.tutor_bridge):
        issues.append("tutor_bridge.repeats_material")
    for example in unit.worked_examples:
        if example.complete and not specific_steps(example.steps):
            issues.append("worked_examples.specific_steps")
    prompts = [normalized(item.prompt) for item in unit.practice_items if item.prompt.strip()]
    if len(set(prompts)) < len(prompts):
        issues.append("practice_items.repeated_prompts")
    for item in unit.practice_items:
        answer, explanation = normalized(item.answer), normalized(item.explanation)
        if answer and answer == normalized(item.prompt):
            issues.append("practice_items.answer_repeats_question")
        if answer and answer == explanation:
            issues.append("practice_items.explanation_repeats_answer")
    for item in unit.misconceptions:
        if item.wrong.strip() and normalized(item.wrong) == normalized(item.correct):
            issues.append("misconceptions.identical_contrast")
    return list(dict.fromkeys(issues))


def repeated_explanations(units: list[Any]) -> list[str]:
    groups = defaultdict(list)
    for unit in units:
        material, bridge = normalized(unit.material_explanation), normalized(unit.tutor_bridge)
        if len(material) >= 12 and len(bridge) >= 12:
            groups[(material, bridge)].append(unit.unit_id)
    return [unit_id for ids in groups.values() if len(ids) > 1 for unit_id in ids]
