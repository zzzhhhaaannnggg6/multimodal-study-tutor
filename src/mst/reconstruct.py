"""Deterministic baseline reconstruction from a project manifest.

This module creates a provenance scaffold that can be enriched by a model
provider later. It never claims that a file was visually inspected or heard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import project_paths, read_json, write_json
from .extract import extract_manifest_sources


def build_scaffold(project_dir: str | Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    if not paths["manifest"].exists():
        raise FileNotFoundError(f"project manifest does not exist: {paths['manifest']}")
    manifest = read_json(paths["manifest"])
    sources = manifest.get("source_manifest", [])
    visuals = [item for item in sources if item.get("kind") in {"slides", "reading"}]
    speech = [item for item in sources if item.get("kind") in {"transcript", "audio"}]
    extracted_pages, extracted_segments = extract_manifest_sources(sources)
    pages = [item.to_dict() for item in extracted_pages]
    audio_segments = [item.to_dict() for item in extracted_segments]
    # Unsupported formats still get a visible unresolved source frame so the
    # UI can explain what is pending instead of silently dropping the input.
    if not pages:
        pages = [
            {
                "visual_id": f"source::{item['source_id']}::p001",
                "source_id": item["source_id"],
                "page": 1,
                "source_page": 1,
                "title": str(item.get("name", "未解析材料")),
                "status": "unresolved",
                "note": "等待页面解析和人工/模型对齐；此条不是教学结论。",
            }
            for item in visuals
        ]
    lesson_map: dict[str, Any] = {
        "schema_version": "1.0",
        "map_kind": "lesson-reconstruction",
        "subject": manifest.get("subject", "generic"),
        "profile": manifest.get("profile", "generic"),
        "source": {"project_id": manifest.get("project_id")},
        "lessons": [],
        "pages": pages,
        "visual_sources": pages,
        "audio_segments": audio_segments,
        "media_segments": audio_segments,
        "units": [],
        "claims": [],
        "assessment_evidence": [],
        "chapter_index": [],
        "notes": {
            "status": "scaffold",
            "message": "仅完成输入清点；请运行解析/对齐步骤后再生成教学主张。",
        },
    }
    write_json(paths["lesson_map"], lesson_map)
    return lesson_map
