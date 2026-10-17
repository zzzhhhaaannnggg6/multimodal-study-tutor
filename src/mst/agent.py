"""Small, provider-neutral study-agent service over a validated lesson map."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import LessonMap
from .providers import MockProvider, ModelProvider


@dataclass
class StudyAgent:
    """Query and explain a lesson without inventing untraceable evidence."""

    lesson_map: LessonMap
    provider: ModelProvider | None = None

    def __post_init__(self) -> None:
        if self.provider is None:
            self.provider = MockProvider()

    def inspect_project(self) -> dict[str, Any]:
        return {
            "subject": self.lesson_map.subject,
            "profile": self.lesson_map.profile,
            "pages": len(self.lesson_map.pages),
            "units": len(self.lesson_map.units),
            "claims": len(self.lesson_map.claims),
            "lessons": len(self.lesson_map.lessons),
        }

    def list_lessons(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.lesson_map.lessons]

    def query_claims(self, query: str) -> list[dict[str, Any]]:
        needle = query.casefold().strip()
        if not needle:
            return []
        hits = []
        for claim in self.lesson_map.claims:
            haystack = " ".join(
                [claim.text, claim.claim_id, claim.unit_id, " ".join(claim.source_labels)]
            ).casefold()
            if needle in haystack:
                hits.append(claim.to_dict())
        return hits

    def find_evidence(self, claim_id: str) -> list[dict[str, Any]]:
        for claim in self.lesson_map.claims:
            if claim.claim_id == claim_id:
                return [item.to_dict() if hasattr(item, "to_dict") else item for item in claim.sources]
        return []

    def explain(self, question: str, *, include_sources: bool = True) -> str:
        matches = self.query_claims(question)
        context = "\n".join(
            f"- {item['text']} [{item['claim_id']}]" for item in matches[:8]
        ) or "未找到直接匹配的主张。"
        source_rule = (
            "只使用给定主张；不确定内容标为待确认，并保留主张 ID。"
            if include_sources
            else "不要扩展超出给定主张的事实。"
        )
        return self.provider.complete(
            system=f"你是可追溯学习导师。{source_rule}",
            user=f"问题：{question}\n相关主张：\n{context}",
        )
