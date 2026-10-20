"""Deterministic multimodal signals used before model enrichment.

The first version of the tutor treated extracted text as if it were the whole
slide.  This module keeps the boundary honest: it does not claim to understand
an image, but records useful, inspectable signals about code, formulas,
connectors, tables and speech functions.  A model or human can then review the
small set of pages and segments that need visual or semantic attention.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.$:+\-/]*|\d+(?:\.\d+)?")
_HAN_RE = re.compile(r"[\u3400-\u9fff]+")
_FORMULA_RE = re.compile(
    r"(?:\\(?:frac|sum|prod|int|sqrt|cdot|times|pm)|"
    r"[A-Za-z][A-Za-z0-9_]*\s*(?:=|:=|\+|-|\*|/|\^|≤|≥|<|>)\s*"
    r"[A-Za-z0-9_(\[\-+]|"
    r"\d+\s*[×x*÷/]\s*\d+|"
    r"[∑∏∫√±≤≥≠∞→←])"
)
_CODE_RE = re.compile(
    r"(?:\b(?:addi|sub|mul|muli|div|lw|sw|ld|sd|beq|jal|jalr|and|or|xor|slli|srli)\b|"
    r"\b(?:int|float|double|char|return|if|else|for|while|always_ff|assign|module)\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*(?:\+=|-=|\*=|/=|=)\s*[^=])"
)
_ARROW_RE = re.compile(r"(?:->|=>|→|⇒|↦|←|⇐|⟶|⟵)")
_TABLE_RE = re.compile(r"\|[^\n|]+\||(?:\t[^\n\t]+){2,}")

_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "into", "then", "when",
    "what", "which", "where", "有", "是", "的", "了", "和", "在", "把", "将",
    "然后", "可以", "一个", "这个", "进行", "通过", "因为", "所以", "我们",
}

_ROLE_RULES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("assessment", ("必考", "考试", "期末", "考点", "作业要求", "评分", "得分", "会考", "test", "exam", "graded"), 5),
    ("correction", ("不是", "不要", "别把", "容易错", "常见错误", "纠正", "误解", "注意不要", "wrong", "mistake"), 4),
    ("definition", ("定义", "称为", "叫做", "是指", "指的是", "也就是", "means", "defined as", "refers to"), 3),
    ("derivation", ("因为", "所以", "因此", "推导", "推出", "于是", "because", "therefore", "derive"), 2),
    ("example", ("例如", "比如", "假设", "举例", "例子", "我们看", "for example", "suppose", "consider"), 2),
    ("emphasis", ("重点", "关键", "注意", "重要", "记住", "核心", "特别", "important", "key"), 2),
    ("question", ("为什么", "如何", "怎么", "想一想", "问题是", "why", "how", "question"), 1),
)

_ROLE_LABELS = {
    "assessment": "评价提示",
    "correction": "纠错提醒",
    "definition": "定义说明",
    "derivation": "推导说明",
    "example": "例题或案例",
    "emphasis": "课堂强调",
    "question": "课堂提问",
    "general": "课堂讲解",
}


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def tokenize(value: str) -> set[str]:
    """Return conservative lexical anchors for cross-language matching."""

    text = str(value or "").lower()
    tokens = {item for item in _ASCII_TOKEN_RE.findall(text) if item not in _STOPWORDS}
    for span in _HAN_RE.findall(text):
        if len(span) <= 4:
            tokens.add(span)
        tokens.update(span[index : index + 2] for index in range(len(span) - 1))
    return {item for item in tokens if len(item) > 1 and item not in _STOPWORDS}


def _context(text: str, match: re.Match[str], radius: int = 42) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return " ".join(text[start:end].split())


def classify_speech_text(text: str) -> dict[str, Any]:
    """Classify the classroom function of a transcript segment.

    The result is a signal, not a teacher claim.  Explicit assessment words
    are retained as evidence for later review; absence of such words never
    implies that a topic will not be assessed.
    """

    source = " ".join(str(text or "").split())
    lower = source.lower()
    scores: Counter[str] = Counter()
    spans: dict[str, list[str]] = {}
    for role, phrases, weight in _ROLE_RULES:
        for phrase in phrases:
            match = re.search(re.escape(phrase), lower, re.IGNORECASE)
            if match:
                scores[role] += weight
                spans.setdefault(role, []).append(_context(source, match))
    ranked = [role for role, score in scores.most_common() if score > 0]
    if not ranked:
        primary = "general"
        confidence = "unresolved"
    else:
        primary = ranked[0]
        top = scores[primary]
        confidence = "high" if top >= 5 or len(ranked) >= 3 else "medium" if top >= 2 else "low"
    return {
        "primary_role": primary,
        "roles": ranked,
        "confidence": confidence,
        "evidence_spans": _unique(span for role in ranked for span in spans.get(role, []))[:4],
        "assessment_signal": "explicit" if "assessment" in scores else "none_observed",
    }


def speech_role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, _ROLE_LABELS["general"])


def visual_signals(
    text: str,
    *,
    shape_counts: Mapping[str, int] | None = None,
    image_count: int = 0,
    connector_count: int = 0,
    diagram_nodes: Sequence[str] | None = None,
    diagram_edges: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Describe observable visual/text structure without claiming OCR or vision."""

    source = "\n".join(str(text or "").splitlines()).strip()
    code_lines = _unique(line.strip() for line in source.splitlines() if _CODE_RE.search(line))
    if not code_lines:
        # PPT XML often flattens line breaks into spaces; retain short code-like
        # fragments so a later model can inspect them as one block.
        code_lines = _unique(match.group(0) for match in _CODE_RE.finditer(source))
    formula_candidates = _unique(match.group(0) for match in _FORMULA_RE.finditer(source))
    arrows = len(_ARROW_RE.findall(source)) + int(connector_count)
    table_hits = len(_TABLE_RE.findall(source))
    lower = source.lower()
    diagram_keywords = _unique(
        keyword
        for keyword in (
            "pc", "alu", "register", "寄存器", "memory", "内存", "mux", "数据通路", "datapath",
            "clock", "时钟", "state", "状态", "fsm", "控制信号", "control", "input", "output",
        )
        if keyword in lower
    )
    counts = {str(key): int(value) for key, value in (shape_counts or {}).items()}
    nodes = _unique(diagram_nodes or [])
    edges = _unique(diagram_edges or [])
    if image_count or counts.get("picture", 0):
        image_count = max(image_count, counts.get("picture", 0))

    cues = []
    if code_lines:
        cues.append("代码/指令")
    if formula_candidates:
        cues.append("公式/符号")
    if arrows or diagram_keywords:
        cues.append("流程/连接")
    if table_hits:
        cues.append("表格")
    if not cues and source:
        cues.append("正文")
    if len(cues) > 1:
        kind = "mixed"
    elif code_lines:
        kind = "code"
    elif formula_candidates:
        kind = "formula"
    elif arrows or diagram_keywords:
        kind = "diagram"
    elif table_hits:
        kind = "table"
    elif source:
        kind = "text"
    elif image_count:
        kind = "image"
    else:
        kind = "unknown"

    if not source and image_count:
        summary = "页面主要是图像；文字提取不足，需要人工或视觉模型复核。"
    elif not source:
        summary = "没有提取到页面文字；可能是扫描页或图形页，需要人工或视觉模型复核。"
    elif kind in {"diagram", "mixed"} and (arrows or diagram_keywords):
        edge_hint = f"发现 {len(edges)} 条节点连接候选" if edges else "检测到流程/连接线索"
        summary = f"{edge_hint}；学习时沿箭头确认起点、经过的部件和终点。"
    elif kind in {"code", "mixed"} and code_lines:
        summary = "检测到代码或指令片段；学习时按行追踪输入、状态变化和写回位置。"
    elif kind in {"formula", "mixed"} and formula_candidates:
        summary = "检测到公式或符号关系；学习时核对变量、运算符、左右两侧和适用条件。"
    elif kind == "table":
        summary = "检测到表格结构；学习时先读表头，再比较每列的条件和结果。"
    else:
        summary = "页面以文字为主；先找标题、定义、条件和结论。"

    review_reasons: list[str] = []
    if image_count:
        review_reasons.append("含图片或截图")
    if not source:
        review_reasons.append("没有可提取文字")
    if arrows or diagram_keywords:
        review_reasons.append("连接关系需要视觉确认")
    if formula_candidates:
        review_reasons.append("公式结构需要核对")
    confidence = "high" if source and (code_lines or formula_candidates or arrows or table_hits) else "medium" if source else "unresolved"
    return {
        "kind": kind,
        "summary": summary,
        "code_lines": code_lines[:20],
        "formula_candidates": formula_candidates[:12],
        "diagram_keywords": diagram_keywords,
        "diagram_nodes": nodes[:40],
        "diagram_edges": edges[:40],
        "arrow_count": arrows,
        "table_hits": table_hits,
        "shape_counts": counts,
        "image_count": image_count,
        "confidence": confidence,
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
    }


def annotate_speech_metadata(metadata: Mapping[str, Any] | None, text: str) -> dict[str, Any]:
    """Merge a speech analysis record without overwriting provider metadata."""

    result = dict(metadata or {})
    result["speech_analysis"] = classify_speech_text(text)
    return result


__all__ = [
    "annotate_speech_metadata",
    "classify_speech_text",
    "speech_role_label",
    "tokenize",
    "visual_signals",
]
