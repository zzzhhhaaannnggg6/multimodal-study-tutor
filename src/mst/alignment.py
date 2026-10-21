"""Conservative page candidates from observable text, never generated prose."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

from .models import Alignment, SpeechSegment, VisualFrame
from .multimodal import classify_speech_text, extract_speech_increment, is_administrative_speech, tokenize


# Normalize words actually present in the two sources, without using
# unverified visual interpretations or generated reading instructions.
_ALIASES = {
    "datapath": ("data path", "数据通路"),
    "regfile": ("register file", "寄存器堆"),
    "register": ("registers", "寄存器"),
    "imem": ("instruction memory", "指令存储器"),
    "dmem": ("data memory", "数据存储器"),
    "pc": ("program counter", "程序计数器"),
    "alu": ("arithmetic logic unit", "算术逻辑单元"),
    "memory": ("内存", "存储器"),
    "controller": ("控制器",),
    "fsm": ("finite state machine", "有限状态机", "状态机"),
    "multicycle": ("multi-cycle", "multi cycle", "多周期"),
    "singlecycle": ("single-cycle", "single cycle", "单周期"),
    "complement": ("two's complement", "补码"),
    "binary": ("二进制",),
    "riscv": ("risc-v",),
}
_GENERIC = {"system", "systems", "course", "lecture", "class", "today", "example", "page",
            "大家", "这个", "那个", "问题", "什么", "就是", "这里", "现在", "这个是", "我们看"}
_BROAD = {"cpu", "pc", "alu", "register", "memory", "computer", "control"}


def _anchors(text: str) -> tuple[set[str], str]:
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b|(?:第\s*\d+\s*页)|\bp\.?\s*\d+\b", " ", text.lower())
    replacements = sorted(((alias, key) for key, aliases in _ALIASES.items() for alias in aliases), key=lambda pair: -len(pair[0]))
    for alias, key in replacements:
        pattern = re.escape(alias) if not alias.isascii() else rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
        normalized = re.sub(pattern, f" {key} ", normalized)
    return {t for t in tokenize(normalized) if not t.replace(".", "").isdigit()} - _GENERIC, normalized


def _independent(shared: set[str], speech: str, page: str) -> set[str]:
    """Overlapping Chinese bigrams are one phrase, not independent evidence."""
    result = set(shared)
    changed = True
    while changed:
        changed = False
        han = sorted(t for t in result if re.fullmatch(r"[\u3400-\u9fff]+", t))
        for left in han:
            for right in han:
                if left == right:
                    continue
                if left in right:
                    result.discard(left)
                    changed = True
                    break
                if left[-1] == right[0] and (joined := left + right[1:]) in speech and joined in page:
                    result.difference_update((left, right))
                    result.add(joined)
                    changed = True
                    break
            if changed:
                break
    return result


def align_speech_to_visuals(pages: Iterable[VisualFrame], segments: Iterable[SpeechSegment]) -> list[SpeechSegment]:
    """Keep uncertain matches out of the lesson's teacher explanations.

    There is no reliable source pairing or sequential model here. A longer
    transcript with very little page support is held for review as a whole,
    rather than spliced into a possibly unrelated lesson.
    """
    page_rows = list(pages)
    segment_rows = list(segments)
    page_data = [(p, *_anchors(f"{p.title or ''}\n{p.text or ''}")) for p in page_rows]
    frequencies = Counter(t for _, tokens, _ in page_data for t in tokens)
    common = {t for t, count in frequencies.items() if len(page_rows) >= 4 and count / len(page_rows) > 0.3}
    groups = defaultdict(list)
    known_pages = {page.visual_id: page for page in page_rows}
    for segment in segment_rows:
        text = segment.text or ""
        segment.metadata = dict(segment.metadata or {})
        segment.metadata["speech_analysis"] = classify_speech_text(text)
        segment.metadata["speech_increment"] = extract_speech_increment(text)
        if segment.status == "verified" and segment.alignment and segment.alignment.status in {"aligned", "covered", "ready"} and segment.alignment.visual_ids and all(ref in known_pages for ref in segment.alignment.visual_ids):
            segment.metadata["speech_increment"] = extract_speech_increment(text, page_text="\n".join(known_pages[ref].text or "" for ref in segment.alignment.visual_ids))
            segment.metadata["alignment_analysis"] = {"method": "preserved_reviewed_alignment", "pairing_status": "reviewed"}
            continue
        if segment.kind == "administrative" or segment.metadata.get("administrative") or is_administrative_speech(text):
            segment.alignment = Alignment(confidence="unresolved", status="navigation", note="导出信息、课堂事务或无教学内容的片段。")
            segment.status = "navigation"
            continue
        tokens, normalized = _anchors(text)
        candidates = []
        for page, page_tokens, page_text in page_data:
            shared = tokens & page_tokens
            anchors = _independent(shared, normalized, page_text)
            specific = anchors - _BROAD - common
            score = len(anchors) + 2 * len(specific)
            if score:
                candidates.append((score, page, anchors, specific, len(shared) / max(1, len(tokens))))
        candidates.sort(key=lambda row: -row[0])
        confidence = "unresolved"
        status = "supplement" if segment.kind == "supplement" else "pending"
        visual_ids = []
        note = "没有足够的页面证据；课次配对或课堂补充关系待确认。"
        if candidates:
            score, page, anchors, specific, coverage = candidates[0]
            margin = score - (candidates[1][0] if len(candidates) > 1 else 0)
            confidence = "low"
            if len(anchors) >= 2 and specific and coverage >= 0.3 and margin >= 2:
                confidence = "high"
                status = "aligned"
            elif len(anchors) == 1 and specific and coverage >= 0.6 and margin >= 2 and any(t.isascii() and len(t) >= 4 for t in specific):
                confidence = "medium"
                status = "aligned"
            visual_ids = [page.visual_id]
            if margin == 0:
                visual_ids = [row[1].visual_id for row in candidates[:3] if row[0] == score]
            note = f"独立文字锚点：{'、'.join(sorted(anchors))}。" + ("词汇匹配，尚未核实课堂顺序。" if status == "aligned" else "证据不足或候选接近，不能确定页码。")
            if status == "aligned":
                segment.metadata["speech_increment"] = extract_speech_increment(text, page_text=page.text or "", page_title=page.title or "")
        segment.alignment = Alignment(visual_ids=visual_ids, confidence=confidence, status=status, note=note)
        segment.status = status
        segment.metadata["alignment_analysis"] = {
            "method": "source_text_anchors",
            "pairing_status": "not_verified",
            "candidates": [{"visual_id": p.visual_id, "score": score, "shared_anchors": sorted(anchors), "specific_anchors": sorted(specific), "speech_coverage": round(coverage, 3)}
                           for score, p, anchors, specific, coverage in candidates[:5]],
        }
        if len(tokens) >= 4:
            groups[segment.source_id or segment.media_id or "unknown"].append(segment)
    for source_id, group in groups.items():
        support = sum(s.status == "aligned" for s in group) / len(group)
        if len(group) >= 8 and support < 0.15:
            for segment in segment_rows:
                if (segment.source_id or segment.media_id or "unknown") != source_id or segment.status in {"navigation", "verified"}:
                    continue
                segment.metadata["alignment_analysis"]["pairing_status"] = "needs_review"
                segment.metadata["alignment_analysis"]["source_support_ratio"] = round(support, 3)
                segment.alignment.status = segment.status = "pending"
                if segment.alignment.visual_ids:
                    segment.alignment.confidence = "low"
                segment.alignment.note = "整份转写与页面的文字支持较少，课次配对待确认；候选不会进入本课教师讲解。"
                segment.metadata["speech_increment"] = extract_speech_increment(segment.text)
    return segment_rows


__all__ = ["align_speech_to_visuals"]
