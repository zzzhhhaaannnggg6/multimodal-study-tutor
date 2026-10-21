"""Deterministic baseline reconstruction from a project manifest.

This module creates a provenance scaffold that can be enriched by a model
provider later. It never claims that a file was visually inspected or heard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .alignment import align_speech_to_visuals
from .render import render_visual_source
from .io import project_paths, read_json, write_json
from .extract import extract_manifest_sources


def inspect_project_visuals(project_dir: str | Path, provider: Any) -> int:
    """Enrich rendered page records with optional vision-model observations."""

    paths = project_paths(project_dir)
    map_path = paths["lesson_map"]
    data = read_json(map_path)
    pages = data.get("pages", data.get("visual_sources", []))
    inspected = 0
    for page in pages:
        if not isinstance(page, dict) or not page.get("image_path"):
            continue
        image_path = paths["root"] / str(page["image_path"])
        if not image_path.is_file():
            continue
        try:
            result = provider.analyze(str(image_path), context=str(page.get("text", "")))
        except Exception as exc:  # preserve the map and make failure visible
            page.setdefault("metadata", {})["vision_error"] = str(exc)
            continue
        if not isinstance(result, dict):
            continue
        metadata = dict(page.get("metadata") or {})
        metadata["vision_analysis"] = result
        page["metadata"] = metadata
        if result.get("kind"):
            page["visual_kind"] = str(result["kind"])
        if result.get("summary"):
            page["visual_summary"] = str(result["summary"])
        evidence = []
        for key in ("nodes", "edges", "formulas", "code"):
            values = result.get(key, [])
            if isinstance(values, list):
                evidence.extend(str(item) for item in values if str(item).strip())
        if evidence:
            page["visual_evidence"] = evidence[:40]
        # Model output remains unverified until a human accepts it.  A model
        # cannot turn a page into a fully trusted source by itself.
        page["needs_visual_review"] = True
        inspected += 1
    data["pages"] = pages
    data["visual_sources"] = pages
    notes = dict(data.get("notes") or {})
    notes["vision_inspection"] = {"provider": getattr(provider, "name", "unknown"), "inspected_pages": inspected}
    data["notes"] = notes
    write_json(map_path, data)
    return inspected


def build_scaffold(project_dir: str | Path, *, render: bool = False, on_progress: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    paths = project_paths(project_dir)
    if not paths["manifest"].exists():
        raise FileNotFoundError(f"project manifest does not exist: {paths['manifest']}")
    manifest = read_json(paths["manifest"])
    sources = manifest.get("source_manifest", [])
    visuals = [item for item in sources if item.get("kind") in {"slides", "reading"}]
    speech = [item for item in sources if item.get("kind") in {"transcript", "audio"}]
    progress = on_progress or (lambda stage, message: None)
    progress("extracting", "正在读取课件与教师转写")
    extraction_issues: list[dict[str, str]] = []
    extracted_pages, extracted_segments = extract_manifest_sources(sources, issues=extraction_issues)
    # Build conservative lexical candidates here so the map contains useful
    # page/time relationships before an optional model or human review.  The
    # alignment object records confidence and keeps weak candidates visible.
    progress("aligning", "正在核对页面与教师讲解的关系")
    extracted_segments = align_speech_to_visuals(extracted_pages, extracted_segments)
    render_notes: list[str] = []
    rendered_count = 0
    if render:
        for source in visuals:
            progress("rendering", f"正在准备页面图像：{source.get('name', '课程材料')}")
            source_path = source.get("path")
            source_id = str(source.get("source_id", "source"))
            if not source_path:
                continue
            result = render_visual_source(source_path, paths["rendered"] / source_id)
            render_notes.extend(result.warnings)
            rendered_count += len(result.images)
            by_page = {
                int(item.page): item
                for item in extracted_pages
                if item.source_id == source_id and str(item.page).isdigit()
            }
            for index, image in enumerate(result.images, 1):
                page = by_page.get(index)
                if page is None:
                    continue
                page.image_path = str(image.relative_to(paths["root"].resolve()))
                page.metadata = dict(page.metadata or {})
                page.metadata["rendered_image"] = page.image_path
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
        "speech_segments": audio_segments,
        "audio_segments": audio_segments,
        "media_segments": audio_segments,
        "units": [],
        "claims": [],
        "assessment_evidence": [],
        "chapter_index": [],
        "notes": {
            "extraction_issues": extraction_issues,
            "status": "scaffold",
            "message": "仅完成输入清点；请运行解析/对齐步骤后再生成教学主张。",
            "rendering": {
                "enabled": render,
                "rendered_pages": rendered_count,
                "warnings": render_notes,
            },
        },
    }
    write_json(paths["lesson_map"], lesson_map)
    return lesson_map
