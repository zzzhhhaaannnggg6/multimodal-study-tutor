"""Student-facing, self-contained study guides.

The lesson map is an evidence ledger for the engine.  A :class:`StudyGuide`
is the separate reading layer a student sees.  The generator is deliberately
conservative: when a model is unavailable it creates a useful, traceable
draft and reports exactly which teaching fields still need enrichment.
"""

from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .io import project_paths, read_json, write_json
from .models import Claim, Evidence, KnowledgeUnit, LessonMap, SpeechSegment, VisualFrame, coerce_lesson_map


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip()


def _split_chain(value: Any) -> list[str]:
    return [part.strip() for part in _text(value).replace("→", "->").split("->") if part.strip()]


@dataclass
class GuideSourceRef:
    """A human-readable link back to the material or classroom."""

    kind: str
    label: str
    ref: str
    page: int | str | None = None
    start: float | str | None = None
    end: float | str | None = None
    quote: str | None = None
    verified: bool = False
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GuideSourceRef":
        return cls(
            kind=_text(value.get("kind"), "material"),
            label=_text(value.get("label"), "材料依据"),
            ref=_text(value.get("ref")),
            page=value.get("page"),
            start=value.get("start"),
            end=value.get("end"),
            quote=value.get("quote"),
            verified=bool(value.get("verified", False)),
            status=_text(value.get("status"), "pending"),
        )


# Public name used in the product plan and integrations.
SourceRef = GuideSourceRef


@dataclass
class WorkedExample:
    title: str
    question: str
    setup: str = ""
    steps: list[str] = field(default_factory=list)
    answer: str = ""
    variation: str = ""
    source_refs: list[GuideSourceRef] = field(default_factory=list)
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "question": self.question,
            "setup": self.setup,
            "steps": self.steps,
            "answer": self.answer,
            "variation": self.variation,
            "source_refs": [item.to_dict() for item in self.source_refs],
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkedExample":
        return cls(
            title=_text(value.get("title"), "代表性例题"),
            question=_text(value.get("question")),
            setup=_text(value.get("setup")),
            steps=[_text(item) for item in _list(value.get("steps"))],
            answer=_text(value.get("answer")),
            variation=_text(value.get("variation")),
            source_refs=[GuideSourceRef.from_dict(item) for item in _list(value.get("source_refs")) if isinstance(item, Mapping)],
            complete=bool(value.get("complete", False)),
        )


@dataclass
class Misconception:
    wrong: str
    correct: str
    correction: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"wrong": self.wrong, "correct": self.correct, "correction": self.correction}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Misconception":
        return cls(_text(value.get("wrong")), _text(value.get("correct")), _text(value.get("correction")))


@dataclass
class PracticeItem:
    practice_id: str
    prompt: str
    kind: str = "retrieval"
    difficulty: str = "基础"
    answer: str = ""
    explanation: str = ""
    unit_id: str | None = None
    source_refs: list[GuideSourceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "practice_id": self.practice_id,
            "prompt": self.prompt,
            "kind": self.kind,
            "difficulty": self.difficulty,
            "answer": self.answer,
            "explanation": self.explanation,
            "unit_id": self.unit_id,
            "source_refs": [item.to_dict() for item in self.source_refs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PracticeItem":
        return cls(
            practice_id=_text(value.get("practice_id"), "practice-01"),
            prompt=_text(value.get("prompt") or value.get("question")),
            kind=_text(value.get("kind"), "retrieval"),
            difficulty=_text(value.get("difficulty"), "基础"),
            answer=_text(value.get("answer")),
            explanation=_text(value.get("explanation")),
            unit_id=value.get("unit_id"),
            source_refs=[GuideSourceRef.from_dict(item) for item in _list(value.get("source_refs")) if isinstance(item, Mapping)],
        )


@dataclass
class LearningUnit:
    unit_id: str
    title: str
    question: str
    one_sentence: str
    why: str
    prerequisites: list[str] = field(default_factory=list)
    visual_refs: list[str] = field(default_factory=list)
    material_explanation: str = ""
    teacher_increment: str = ""
    tutor_bridge: str = ""
    step_chain: list[str] = field(default_factory=list)
    worked_examples: list[WorkedExample] = field(default_factory=list)
    misconceptions: list[Misconception] = field(default_factory=list)
    practice_items: list[PracticeItem] = field(default_factory=list)
    priority_label: str = "重点理解"
    assessment_signal: str = "尚未观察到评价信号"
    source_refs: list[GuideSourceRef] = field(default_factory=list)
    status: str = "draft"
    internal_understanding_level: str = "U1"
    internal_assessment_level: str = "E0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "title": self.title,
            "question": self.question,
            "one_sentence": self.one_sentence,
            "why": self.why,
            "prerequisites": self.prerequisites,
            "visual_refs": self.visual_refs,
            "material_explanation": self.material_explanation,
            "teacher_increment": self.teacher_increment,
            "tutor_bridge": self.tutor_bridge,
            "step_chain": self.step_chain,
            "worked_examples": [item.to_dict() for item in self.worked_examples],
            "misconceptions": [item.to_dict() for item in self.misconceptions],
            "practice_items": [item.to_dict() for item in self.practice_items],
            "priority_label": self.priority_label,
            "assessment_signal": self.assessment_signal,
            "source_refs": [item.to_dict() for item in self.source_refs],
            "status": self.status,
            "internal_understanding_level": self.internal_understanding_level,
            "internal_assessment_level": self.internal_assessment_level,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LearningUnit":
        return cls(
            unit_id=_text(value.get("unit_id")),
            title=_text(value.get("title"), "未命名单元"),
            question=_text(value.get("question")),
            one_sentence=_text(value.get("one_sentence")),
            why=_text(value.get("why")),
            prerequisites=[_text(item) for item in _list(value.get("prerequisites"))],
            visual_refs=[_text(item) for item in _list(value.get("visual_refs") or value.get("visual_ids"))],
            material_explanation=_text(value.get("material_explanation")),
            teacher_increment=_text(value.get("teacher_increment")),
            tutor_bridge=_text(value.get("tutor_bridge")),
            step_chain=[_text(item) for item in _list(value.get("step_chain"))],
            worked_examples=[WorkedExample.from_dict(item) for item in _list(value.get("worked_examples")) if isinstance(item, Mapping)],
            misconceptions=[Misconception.from_dict(item) for item in _list(value.get("misconceptions")) if isinstance(item, Mapping)],
            practice_items=[PracticeItem.from_dict(item) for item in _list(value.get("practice_items")) if isinstance(item, Mapping)],
            priority_label=_text(value.get("priority_label"), "重点理解"),
            assessment_signal=_text(value.get("assessment_signal"), "尚未观察到评价信号"),
            source_refs=[GuideSourceRef.from_dict(item) for item in _list(value.get("source_refs")) if isinstance(item, Mapping)],
            status=_text(value.get("status"), "draft"),
            internal_understanding_level=_text(value.get("internal_understanding_level"), "U1"),
            internal_assessment_level=_text(value.get("internal_assessment_level"), "E0"),
        )


@dataclass
class StudyRoute:
    central_question: str
    outcomes: list[str]
    prerequisites: list[str]
    chain: list[str]
    estimated_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StudyRoute":
        return cls(
            central_question=_text(value.get("central_question")),
            outcomes=[_text(item) for item in _list(value.get("outcomes"))],
            prerequisites=[_text(item) for item in _list(value.get("prerequisites"))],
            chain=[_text(item) for item in _list(value.get("chain"))],
            estimated_minutes=int(value.get("estimated_minutes", 15)),
        )


@dataclass
class GenerationReport:
    status: str
    provider: str
    total_pages: int
    covered_pages: int
    total_segments: int
    aligned_segments: int
    unresolved_items: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationReport":
        return cls(
            status=_text(value.get("status"), "draft"),
            provider=_text(value.get("provider"), "none"),
            total_pages=int(value.get("total_pages", 0)),
            covered_pages=int(value.get("covered_pages", 0)),
            total_segments=int(value.get("total_segments", 0)),
            aligned_segments=int(value.get("aligned_segments", 0)),
            unresolved_items=[_text(item) for item in _list(value.get("unresolved_items"))],
            missing_fields=[_text(item) for item in _list(value.get("missing_fields"))],
            warnings=[_text(item) for item in _list(value.get("warnings"))],
        )


@dataclass
class StudyGuide:
    guide_version: str
    guide_kind: str
    lesson_id: str | None
    title: str
    subject: str
    profile: str
    language: str
    route: StudyRoute
    units: list[LearningUnit]
    review_items: list[PracticeItem]
    source_index: list[GuideSourceRef]
    report: GenerationReport
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "guide_version": self.guide_version,
            "guide_kind": self.guide_kind,
            "lesson_id": self.lesson_id,
            "title": self.title,
            "subject": self.subject,
            "profile": self.profile,
            "language": self.language,
            "route": self.route.to_dict(),
            "units": [item.to_dict() for item in self.units],
            "review_items": [item.to_dict() for item in self.review_items],
            "source_index": [item.to_dict() for item in self.source_index],
            "generation_report": self.report.to_dict(),
            "notes": self.notes,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StudyGuide":
        return cls(
            guide_version=_text(value.get("guide_version"), "1.0"),
            guide_kind=_text(value.get("guide_kind"), "student-study-guide"),
            lesson_id=value.get("lesson_id"),
            title=_text(value.get("title"), "自学讲义"),
            subject=_text(value.get("subject"), "generic"),
            profile=_text(value.get("profile"), "generic"),
            language=_text(value.get("language"), "zh-CN"),
            route=StudyRoute.from_dict(value.get("route", {})),
            units=[LearningUnit.from_dict(item) for item in _list(value.get("units")) if isinstance(item, Mapping)],
            review_items=[PracticeItem.from_dict(item) for item in _list(value.get("review_items")) if isinstance(item, Mapping)],
            source_index=[GuideSourceRef.from_dict(item) for item in _list(value.get("source_index")) if isinstance(item, Mapping)],
            report=GenerationReport.from_dict(value.get("generation_report", {})),
            notes=[_text(item) for item in _list(value.get("notes"))],
        )

    @classmethod
    def from_json(cls, value: str | Path) -> "StudyGuide":
        path = Path(value)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write_json(self, path: str | Path) -> Path:
        return write_json(path, self.to_dict())


@dataclass
class GuideDiagnostic:
    severity: str
    code: str
    path: str
    message: str


@dataclass
class GuideValidationReport:
    diagnostics: list[GuideDiagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[GuideDiagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    @property
    def warnings(self) -> list[GuideDiagnostic]:
        return [item for item in self.diagnostics if item.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _source_from_evidence(evidence: Evidence) -> GuideSourceRef:
    kind = evidence.kind
    if "teacher" in kind or "transcript" in kind or "audio" in kind:
        label = "教师补充"
    elif "tutor" in kind or "synthesis" in kind:
        label = "导师补链"
    else:
        label = "材料依据"
    ref = evidence.ref or evidence.locator or evidence.source_id or "待定位"
    return GuideSourceRef(
        kind=kind,
        label=label,
        ref=ref,
        page=evidence.page,
        start=evidence.start,
        end=evidence.end,
        quote=evidence.text,
        verified=evidence.verified,
        status=evidence.status,
    )


def _page_ref(page: VisualFrame) -> GuideSourceRef:
    page_number = page.page if page.page is not None else page.source_page
    return GuideSourceRef(
        kind="material",
        label="材料依据",
        ref=page.visual_id,
        page=page_number,
        quote=page.text,
        verified=page.status in {"covered", "verified"},
        status=page.status,
    )


def _segment_ref(segment: SpeechSegment) -> GuideSourceRef:
    return GuideSourceRef(
        kind="classroom_transcript",
        label="教师补充",
        ref=segment.segment_id,
        start=segment.start,
        end=segment.end,
        quote=segment.text,
        verified=segment.status in {"aligned", "covered", "verified"},
        status=segment.status,
    )


def _priority(level: str) -> str:
    return {
        "U3": "必须掌握：理解主干",
        "U2": "重点应用：需要会用",
        "U1": "补链知识：帮助理解",
        "U0": "背景了解",
    }.get(level, "重点理解")


def _assessment(level: str) -> str:
    return {
        "E3": "明确评价要求（已有来源证据）",
        "E2": "较强评价信号（不等于必考）",
        "E1": "课堂强调，但尚不足以判断考试要求",
        "E-": "明确排除当前评价范围（已有来源证据）",
        "E0": "尚未观察到评价信号",
    }.get(level, "尚未观察到评价信号")


def _unit_segments(unit: KnowledgeUnit, segments: Sequence[SpeechSegment]) -> list[SpeechSegment]:
    ids = set(unit.segment_ids)
    return [item for item in segments if item.segment_id in ids]


def _unit_pages(unit: KnowledgeUnit, pages: Sequence[VisualFrame]) -> list[VisualFrame]:
    ids = set(unit.visual_ids)
    return [item for item in pages if item.visual_id in ids]


def _infer_units(pages: Sequence[VisualFrame], segments: Sequence[SpeechSegment]) -> list[KnowledgeUnit]:
    """Create conservative page groups when no semantic unit map exists.

    This keeps a large deck readable offline without pretending that page
    boundaries are the teacher's conceptual boundaries.  A model can later
    merge or split these temporary groups.
    """

    if not pages:
        if not segments:
            return []
        return [
            KnowledgeUnit(
                unit_id="inferred::u001",
                title="课堂转写主线（待拆分）",
                segment_ids=[item.segment_id for item in segments],
                understanding_level="U3",
                exam_evidence_level="E0",
                logic_chain="课堂问题 → 解释过程 → 应用结果",
                learner_action="能够复述课堂主线，并把它应用到一个新情境。",
                transfer_question="请把课堂主线迁移到一个新情境。",
                status="draft",
            )
        ]
    group_size = 1 if len(pages) <= 8 else max(2, math.ceil(len(pages) / 12))
    groups: list[KnowledgeUnit] = []
    for start in range(0, len(pages), group_size):
        chunk = list(pages[start : start + group_size])
        ids = {item.visual_id for item in chunk}
        linked_segments = [
            item.segment_id
            for item in segments
            if item.alignment and ids.intersection(item.alignment.visual_ids)
        ]
        first = chunk[0]
        last = chunk[-1]
        page_label = f"第 {first.page} 页" if first.page == last.page else f"第 {first.page}–{last.page} 页"
        title = _text(first.title, f"材料片段 {page_label}")
        if len(chunk) > 1:
            title = f"{title}（{page_label}）"
        groups.append(
            KnowledgeUnit(
                unit_id=f"inferred::u{len(groups) + 1:03d}",
                title=title,
                visual_ids=[item.visual_id for item in chunk],
                segment_ids=linked_segments,
                understanding_level="U3" if len(groups) == 0 else "U2",
                exam_evidence_level="E0",
                logic_chain="观察材料 → 识别对象或关系 → 检查结论",
                learner_action="能够用自己的话解释这一组材料，并说明它在整节课中的作用。",
                transfer_question="换一个相近案例时，哪一步需要重新检查？",
                status="draft",
            )
        )
    return groups


def _make_example(unit: KnowledgeUnit, refs: list[GuideSourceRef]) -> WorkedExample:
    raw = _text(unit.representative_example or unit.counterexample)
    chain = _split_chain(unit.logic_chain)
    steps = [f"先做：{part}" for part in chain]
    if raw:
        question = raw
        setup = "先把题目或新案例中的已知条件写出来，再沿着本单元的逻辑链检查。"
        answer = _text(unit.learner_action, "根据逻辑链说明证据、过程和结果之间的关系。")
    else:
        question = "请把本单元的逻辑链应用到一个新情境。"
        setup = "题目材料不足，先写出对象、条件和要解释的结果。"
        answer = "根据本单元的步骤逐项说明；当前地图没有提供完整演算过程。"
    return WorkedExample(
        title="代表性例子（生成草稿）",
        question=question,
        setup=setup,
        steps=steps,
        answer=answer,
        variation=_text(unit.transfer_question, "换一个条件后，检查哪一步会改变。"),
        source_refs=refs,
        complete=bool(raw and len(steps) >= 2 and answer),
    )


def _make_practice(unit: KnowledgeUnit, refs: list[GuideSourceRef], suffix: str = "01") -> PracticeItem:
    prompt = _text(unit.transfer_question or unit.learner_action, "请用自己的话复述本单元的核心链条。")
    answer = _text(unit.learner_action or unit.logic_chain, "答案需要覆盖本单元的核心步骤。")
    explanation = _text(unit.logic_chain, "先说明对象，再说明关系或过程，最后检查结果和限制。")
    return PracticeItem(
        practice_id=f"{unit.unit_id}::practice-{suffix}",
        prompt=prompt,
        kind="transfer" if unit.transfer_question else "retrieval",
        difficulty="基础迁移",
        answer=answer,
        explanation=explanation,
        unit_id=unit.unit_id,
        source_refs=refs,
    )


def _enrich_with_provider(unit: LearningUnit, provider: Any, context: str) -> tuple[LearningUnit, str | None]:
    """Ask an optional provider for learner prose, preserving the scaffold on failure."""

    prompt = {
        "unit_id": unit.unit_id,
        "title": unit.title,
        "question": unit.question,
        "existing": unit.to_dict(),
        "source_context": context,
        "required": [
            "one_sentence", "why", "material_explanation", "teacher_increment",
            "tutor_bridge", "step_chain", "worked_examples", "misconceptions",
            "practice_items",
        ],
    }
    system = (
        "你是面向没有听课的大学生的中文导师。只依据给定材料和课堂片段，"
        "把知识单元写成可以独立学习的内容。导师补链必须明确标注；不能伪造教师原话、"
        "考试承诺、页码或时间戳。返回 JSON 对象，不要返回 Markdown。"
    )
    try:
        raw = provider.complete(system=system, user=json.dumps(prompt, ensure_ascii=False), response_format="json")
        data = json.loads(raw)
    except Exception as exc:  # provider errors should leave a usable draft
        return unit, f"模型补全失败：{exc}"
    if not isinstance(data, Mapping):
        return unit, "模型返回不是 JSON 对象"
    merged = unit.to_dict()
    for key in ("question", "one_sentence", "why", "material_explanation", "teacher_increment", "tutor_bridge", "priority_label", "assessment_signal"):
        if data.get(key):
            merged[key] = data[key]
    for key in ("prerequisites", "step_chain"):
        if isinstance(data.get(key), list) and data[key]:
            merged[key] = data[key]
    for key, cls in (("worked_examples", WorkedExample), ("misconceptions", Misconception), ("practice_items", PracticeItem)):
        if isinstance(data.get(key), list) and data[key]:
            merged[key] = [item.to_dict() if hasattr(item, "to_dict") else item for item in data[key]]
    enriched = LearningUnit.from_dict(merged)
    enriched.status = "ready"
    return enriched, None


def generate_study_guide(
    lesson_map: LessonMap | Mapping[str, Any] | str | Path,
    provider: Any | None = None,
) -> StudyGuide:
    """Generate a learner-facing guide from a validated lesson map.

    Without a provider the result is intentionally marked ``draft``.  This is
    useful for offline inspection but never claims that a complete lecture has
    been reconstructed.
    """

    lesson = coerce_lesson_map(lesson_map)
    pages = lesson.pages
    segments = lesson.speech_segments
    claims_by_unit: dict[str, list[Claim]] = {}
    for claim in lesson.claims:
        if claim.unit_id:
            claims_by_unit.setdefault(claim.unit_id, []).append(claim)
    page_by_id = {item.visual_id: item for item in pages}
    segment_by_id = {item.segment_id: item for item in segments}
    source_units = list(lesson.units)
    inferred_units = False
    if not source_units and (pages or segments):
        inferred_units = True
        source_units = _infer_units(pages, segments)
    units: list[LearningUnit] = []
    missing: list[str] = []
    warnings: list[str] = []

    for source_unit in source_units:
        unit_pages = _unit_pages(source_unit, pages)
        unit_segments = _unit_segments(source_unit, segments)
        refs = [_page_ref(item) for item in unit_pages]
        refs.extend(_segment_ref(item) for item in unit_segments)
        for claim in claims_by_unit.get(source_unit.unit_id, []):
            refs.extend(_source_from_evidence(item) for item in claim.sources)
        refs = list({item.ref: item for item in refs}.values())
        chain = _split_chain(source_unit.logic_chain)
        title = _text(source_unit.title, "未命名知识单元")
        one_sentence = _text(source_unit.learner_action, f"理解“{title}”的核心对象、关系和应用方式。")
        question = f"{title}到底要解决什么问题？"
        why = f"先解决这个问题，后面的内容才能沿着“{_text(source_unit.logic_chain, '对象 → 过程 → 结果')}”继续推理。"
        material = "\n".join(_text(item.text) for item in unit_pages if _text(item.text))
        teacher = "\n".join(_text(item.text) for item in unit_segments if _text(item.text))
        bridge = f"把材料中的信息连起来：{_text(source_unit.logic_chain, '先确定对象，再追踪关系，最后检查结果。')}"
        misconceptions = []
        if source_unit.counterexample:
            misconceptions.append(Misconception("把反例当成普遍结论", source_unit.counterexample, "先检查成立条件，再决定能否推广。"))
        unit = LearningUnit(
            unit_id=source_unit.unit_id,
            title=title,
            question=question,
            one_sentence=one_sentence,
            why=why,
            prerequisites=[_text(item) for item in source_unit.prerequisite_ids],
            visual_refs=[item.visual_id for item in unit_pages],
            material_explanation=material or "材料文字尚未提取；请查看来源页或等待视觉解析。",
            teacher_increment=teacher or "没有可定位的教师补充片段。",
            tutor_bridge=bridge,
            step_chain=chain or ["确定对象", "追踪关系或过程", "检查结果与限制"],
            worked_examples=[_make_example(source_unit, refs)],
            misconceptions=misconceptions,
            practice_items=[_make_practice(source_unit, refs)],
            priority_label=_priority(source_unit.understanding_level),
            assessment_signal=_assessment(source_unit.exam_evidence_level),
            source_refs=refs,
            status="draft",
            internal_understanding_level=source_unit.understanding_level,
            internal_assessment_level=source_unit.exam_evidence_level,
        )
        if provider is not None:
            context = "\n".join([material, teacher, *[claim.text for claim in claims_by_unit.get(source_unit.unit_id, [])]])
            unit, warning = _enrich_with_provider(unit, provider, context)
            if warning:
                warnings.append(f"{unit.unit_id}: {warning}")
        required = [
            ("question", unit.question),
            ("one_sentence", unit.one_sentence),
            ("why", unit.why),
            ("step_chain", unit.step_chain),
            ("worked_examples", unit.worked_examples),
            ("practice_items", unit.practice_items),
            ("source_refs", unit.source_refs),
        ]
        for name, value in required:
            if not value:
                missing.append(f"{unit.unit_id}.{name}")
        if not unit.worked_examples or not all(item.complete for item in unit.worked_examples):
            missing.append(f"{unit.unit_id}.worked_examples.complete")
        units.append(unit)

    source_index = [_page_ref(item) for item in pages]
    source_index.extend(_segment_ref(item) for item in segments)
    outcomes = [item.one_sentence for item in units[:4]]
    chain = [item.title for item in units]
    route = StudyRoute(
        central_question=_text(lesson.title, "这节课要把哪些材料信息变成可以使用的知识？"),
        outcomes=outcomes,
        prerequisites=list(dict.fromkeys(item for unit in units for item in unit.prerequisites)),
        chain=chain,
        estimated_minutes=max(10, len(units) * 8),
    )
    review_items = [item for unit in units for item in unit.practice_items]
    aligned = sum(1 for item in segments if item.alignment and item.alignment.status in {"aligned", "covered", "verified"})
    covered_pages = sum(1 for item in pages if item.status in {"covered", "verified", "merged"})
    status = "complete" if provider is not None and units and not missing and not warnings else "draft"
    if not units:
        status = "needs-content"
        warnings.append("lesson-map 没有可解析的页面或知识单元；当前只能生成输入骨架，不能声称完成课程讲解。")
    elif inferred_units:
        warnings.append("lesson-map 没有知识单元；已从页面建立一个待模型拆分的临时单元。")
    if units and provider is None:
        warnings.append("未提供文本模型；已生成可追溯教学草稿，例题和补链仍需模型或人工复核。")
    report = GenerationReport(
        status=status,
        provider=getattr(provider, "name", "none") if provider is not None else "none",
        total_pages=len(pages),
        covered_pages=covered_pages,
        total_segments=len(segments),
        aligned_segments=aligned,
        unresolved_items=[item.visual_id for item in pages if item.status in {"pending", "unresolved"}],
        missing_fields=missing,
        warnings=warnings,
    )
    notes = [
        "学生主阅读层不显示内部 U/E 等级；来源详情保留在每个知识单元下方。",
        "没有模型或完整证据时，状态为草稿，不能替代完整授课。",
    ]
    return StudyGuide(
        guide_version="1.0",
        guide_kind="student-study-guide",
        lesson_id=lesson.lesson_id,
        title=_text(lesson.title, f"{lesson.subject} 自学讲义"),
        subject=lesson.subject,
        profile=lesson.profile,
        language="zh-CN",
        route=route,
        units=units,
        review_items=review_items,
        source_index=source_index,
        report=report,
        notes=notes,
    )


def validate_study_guide(value: StudyGuide | Mapping[str, Any] | str | Path, *, strict: bool = False) -> GuideValidationReport:
    guide = value if isinstance(value, StudyGuide) else StudyGuide.from_json(value) if isinstance(value, (str, Path)) else StudyGuide.from_dict(value)
    report = GuideValidationReport()
    if not guide.title.strip():
        report.diagnostics.append(GuideDiagnostic("error", "guide.title", "$.title", "学生讲义必须有标题"))
    if not guide.units:
        report.diagnostics.append(GuideDiagnostic("error" if strict else "warning", "units.empty", "$.units", "没有知识单元，无法完成自学讲解"))
    for index, unit in enumerate(guide.units):
        path = f"$.units[{index}]"
        for name in ("question", "one_sentence", "why", "step_chain", "worked_examples", "practice_items", "source_refs"):
            if not getattr(unit, name):
                report.diagnostics.append(GuideDiagnostic("error", "unit.incomplete", f"{path}.{name}", "核心知识单元缺少独立学习所需内容"))
        if not unit.worked_examples or not all(example.complete for example in unit.worked_examples):
            report.diagnostics.append(GuideDiagnostic("error" if strict else "warning", "example.incomplete", f"{path}.worked_examples", "至少一个例题还没有完整步骤或答案"))
        for item_index, practice in enumerate(unit.practice_items):
            if not practice.answer or not practice.explanation:
                report.diagnostics.append(GuideDiagnostic("error", "practice.answer_missing", f"{path}.practice_items[{item_index}]", "练习必须有答案和解析"))
    if guide.report.status == "draft":
        report.diagnostics.append(GuideDiagnostic("warning", "guide.draft", "$.generation_report.status", "这是教学草稿，尚未通过完整讲义质量门槛"))
    return report


def _md_source(ref: GuideSourceRef) -> str:
    location = ref.ref
    if ref.page is not None:
        location = f"p.{ref.page}"
    elif ref.start is not None:
        location = f"{ref.start}–{ref.end or '?'}"
    return f"`{ref.label}`（{location}）"


def render_markdown(guide: StudyGuide) -> str:
    """Render a readable, print-friendly Chinese study handout."""

    lines = [f"# {guide.title}", "", f"> 这是一份面向自学的讲义。预计学习时间：{guide.route.estimated_minutes} 分钟。", ""]
    if guide.report.status != "complete":
        lines.extend(["> **当前状态：教学草稿**。部分例题、补链或教师内容仍需模型/人工复核；请不要把未确认内容当作考试承诺。", ""])
    lines.extend(["## 先看学习路线", "", f"**本节要解决的问题：** {guide.route.central_question}", ""])
    if guide.route.outcomes:
        lines.append("学完后，你应当能够：")
        lines.extend(f"- {item}" for item in guide.route.outcomes)
        lines.append("")
    if guide.route.prerequisites:
        lines.extend([f"**先修知识：** {'；'.join(guide.route.prerequisites)}", ""])
    if guide.route.chain:
        lines.extend(["**学习顺序：** " + " → ".join(guide.route.chain), ""])
    for index, unit in enumerate(guide.units, 1):
        lines.extend([f"## {index}. {unit.title}", "", f"> **先记住一句话：** {unit.one_sentence}", "", f"### 1. 先回答：{unit.question}", "", unit.why, ""])
        if unit.prerequisites:
            lines.extend([f"**需要先会：** {'；'.join(unit.prerequisites)}", ""])
        lines.extend(["### 2. 看材料", "", unit.material_explanation, ""])
        lines.extend(["### 3. 课堂补充", "", unit.teacher_increment, ""])
        lines.extend(["### 4. 把逻辑补完整", "", unit.tutor_bridge, ""])
        if unit.step_chain:
            lines.append("过程可以按下面顺序检查：")
            lines.extend(f"{step_index}. {step}" for step_index, step in enumerate(unit.step_chain, 1))
            lines.append("")
        for example in unit.worked_examples:
            lines.extend(["### 5. 完整例题", "", f"**题目：** {example.question}", "", example.setup, ""])
            if example.steps:
                lines.append("**一步一步做：**")
                lines.extend(f"{step_index}. {step}" for step_index, step in enumerate(example.steps, 1))
                lines.append("")
            lines.extend([f"**答案：** {example.answer}", "", f"**换一个条件：** {example.variation}", ""])
        if unit.misconceptions:
            lines.extend(["### 6. 最容易错在哪里", "", "| 错误想法 | 正确判断 | 纠正动作 |", "| --- | --- | --- |"])
            lines.extend(f"| {item.wrong} | {item.correct} | {item.correction} |" for item in unit.misconceptions)
            lines.append("")
        lines.extend(["### 7. 先自己回答", ""])
        for practice in unit.practice_items:
            lines.extend([f"**问题：** {practice.prompt}", "", "<details><summary>展开答案与解析</summary>", "", f"**答案：** {practice.answer}", "", f"**解析：** {practice.explanation}", "", "</details>", ""])
        lines.extend([f"**学习重点：** {unit.priority_label}", f"**评价信息：** {unit.assessment_signal}", ""])
        if unit.source_refs:
            lines.append("**来源：** " + "；".join(_md_source(item) for item in unit.source_refs))
            lines.append("")
    lines.extend(["## 课后闭卷复习", "", "合上材料后，按学习顺序写出本节的主线：", "", " → ".join(guide.route.chain) or "暂无主线", ""])
    for index, item in enumerate(guide.review_items, 1):
        lines.extend([f"### 复习题 {index}", "", item.prompt, "", "<details><summary>查看答案</summary>", "", f"{item.answer}", "", item.explanation, "", "</details>", ""])
    lines.extend(["## 来源与状态", "", f"- 页面覆盖：{guide.report.covered_pages}/{guide.report.total_pages}", f"- 时间片段对齐：{guide.report.aligned_segments}/{guide.report.total_segments}"])
    if guide.report.warnings:
        lines.append("- 需要复核：" + "；".join(guide.report.warnings))
    return "\n".join(lines).strip() + "\n"


def render_html(guide: StudyGuide) -> str:
    """Render the same guide as a standalone browser document."""

    body = render_markdown(guide)
    # Keep the export dependency-free.  The web app provides the interactive
    # version; this standalone output intentionally preserves readable HTML.
    paragraphs = []
    for line in body.splitlines():
        if line.startswith("# "):
            paragraphs.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            paragraphs.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            paragraphs.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("> "):
            paragraphs.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
        elif line.startswith("- "):
            paragraphs.append(f"<li>{html.escape(line[2:])}</li>")
        elif line and not line.startswith("|") and not line.startswith("<details") and not line.startswith("</details") and not line.startswith("<summary"):
            paragraphs.append(f"<p>{html.escape(line)}</p>")
    return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>" + html.escape(guide.title) + "</title><style>body{max-width:820px;margin:40px auto;padding:0 22px;font:16px/1.8 system-ui,sans-serif;color:#26352c;background:#fbfcf8}h1{line-height:1.25}h2{margin-top:2.3em;border-bottom:1px solid #dbe5dc;padding-bottom:.35em}h3{margin-top:1.6em;color:#315c43}blockquote{margin:16px 0;padding:10px 15px;border-left:4px solid #d47758;background:#fff5ef}li{margin:5px 0}code{background:#eef3ee;padding:2px 4px}</style></head><body>" + "\n".join(paragraphs) + "</body></html>"


def load_project_guide(project_dir: str | Path) -> StudyGuide:
    paths = project_paths(project_dir)
    guide_path = paths["study_guide"]
    if not guide_path.exists():
        raise FileNotFoundError(f"study guide does not exist: {guide_path}; run study generate first")
    return StudyGuide.from_json(guide_path)


def generate_project_guide(project_dir: str | Path, provider: Any | None = None) -> StudyGuide:
    paths = project_paths(project_dir)
    map_path = paths["lesson_map"]
    if not map_path.exists() and paths["root"].joinpath("lesson-map.json").exists():
        map_path = paths["root"] / "lesson-map.json"
    guide = generate_study_guide(read_json(map_path), provider)
    guide.write_json(paths["study_guide"])
    write_json(paths["generation_report"], guide.report.to_dict())
    return guide


__all__ = [
    "GenerationReport",
    "GuideDiagnostic",
    "GuideSourceRef",
    "GuideValidationReport",
    "LearningUnit",
    "Misconception",
    "PracticeItem",
    "StudyGuide",
    "StudyRoute",
    "SourceRef",
    "WorkedExample",
    "generate_project_guide",
    "generate_study_guide",
    "load_project_guide",
    "render_html",
    "render_markdown",
    "validate_study_guide",
]
