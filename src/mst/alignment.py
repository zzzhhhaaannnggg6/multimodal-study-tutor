"""Evidence-aware semantic alignment between transcript segments and pages."""

from __future__ import annotations

from typing import Iterable

from .models import Alignment, SpeechSegment, VisualFrame
from .multimodal import classify_speech_text, tokenize


def _score(segment: SpeechSegment, page: VisualFrame) -> tuple[int, set[str], set[str]]:
    segment_tokens = tokenize(segment.text or segment.transcript or "")
    page_tokens = tokenize(" ".join(item for item in (page.title, page.text) if item))
    shared = segment_tokens & page_tokens
    title_tokens = tokenize(page.title or "")
    title_shared = shared & title_tokens
    # Code identifiers, numbers and formula anchors carry more meaning than
    # generic classroom words.  This is still a lexical candidate, never a
    # proof that the teacher was discussing the page.
    strong = {item for item in shared if any(char.isdigit() for char in item) or any(char in item for char in "_+-*/=→")}
    score = len(shared) + (2 * len(title_shared)) + (2 * len(strong))
    return score, shared, strong


def align_speech_to_visuals(
    pages: Iterable[VisualFrame],
    segments: Iterable[SpeechSegment],
) -> list[SpeechSegment]:
    """Attach conservative page candidates to transcript segments.

    A segment is marked ``aligned`` only when it has lexical anchors on a
    page.  Segments with meaningful classroom speech but no page anchors stay
    ``supplement``; empty or unusable segments remain ``unresolved``.  This
    makes weak alignment visible instead of assigning every sentence to a
    nearby slide by position alone.
    """

    page_rows = list(pages)
    for segment in segments:
        text = " ".join(str(segment.text or segment.transcript or "").split())
        analysis = classify_speech_text(text)
        if not text:
            segment.alignment = Alignment(
                confidence="unresolved",
                status="unresolved",
                note="语音片段没有可用于对齐的文字。",
            )
            segment.status = "unresolved"
            continue
        candidates = []
        for page in page_rows:
            score, shared, strong = _score(segment, page)
            if score:
                candidates.append((score, page, shared, strong))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            segment.alignment = Alignment(
                confidence="unresolved",
                status="supplement",
                note="没有找到页面词汇锚点；保留为课堂补充，不能声称对应某页。",
            )
            segment.status = "supplement"
            continue
        best_score, best_page, shared, strong = candidates[0]
        second_score = candidates[1][0] if len(candidates) > 1 else 0
        margin = best_score - second_score
        if best_score >= 6 and margin >= 2:
            confidence = "high"
        elif best_score >= 3 and (margin >= 1 or best_score >= 5):
            confidence = "medium"
        else:
            confidence = "low"
        status = "aligned"
        candidate_text = ", ".join(sorted(shared)[:8])
        note = f"词汇锚点：{candidate_text or '未列出'}；候选得分 {best_score}。"
        if confidence == "low":
            note += " 仅作弱候选，需人工复核。"
        segment.alignment = Alignment(
            visual_ids=[best_page.visual_id],
            confidence=confidence,
            status=status,
            note=note,
        )
        segment.status = "aligned" if confidence in {"high", "medium"} else "pending"
        segment.metadata = dict(segment.metadata or {})
        segment.metadata.setdefault("speech_analysis", analysis)
        segment.metadata["alignment_analysis"] = {
            "candidate_count": len(candidates),
            "best_score": best_score,
            "margin": margin,
            "strong_anchors": sorted(strong),
            "candidates": [
                {
                    "visual_id": candidate_page.visual_id,
                    "score": candidate_score,
                    "shared_anchors": sorted(candidate_shared)[:12],
                }
                for candidate_score, candidate_page, candidate_shared, _candidate_strong in candidates[:5]
            ],
        }
    return list(segments)


__all__ = ["align_speech_to_visuals"]
