"""Human-readable exports for local study projects."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from .io import active_project_dir, project_paths, read_json
from .guide import StudyGuide, load_project_guide, render_html, render_markdown

HTML_IMAGE_BUDGET = 256 * 1024 * 1024
HTML_SINGLE_IMAGE_LIMIT = 32 * 1024 * 1024


def guide_image_data(project: Path, guide: StudyGuide) -> tuple[dict[str, str], list[str]]:
    """Embed only local rendered images, once; never arbitrary source paths."""
    project = project.resolve()
    root = (project / "derived/rendered").resolve()
    images, notes, seen = {}, [], set()
    used = 0
    refs = [*guide.source_index, *(ref for unit in guide.units for ref in unit.source_refs)]
    for ref in refs:
        relative = ref.image_path
        if not relative or relative in seen:
            continue
        seen.add(relative)
        location = f"第 {ref.page} 页" if ref.page is not None else "一页材料"
        try:
            parts = relative.split("/")
            if (not root.is_relative_to(project) or not relative.startswith("derived/rendered/")
                    or any(part in {"", ".", ".."} or "\\" in part for part in parts)):
                raise ValueError("not a relative rendered image")
            target = (project / relative).resolve()
            if not target.is_relative_to(root) or target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("not a rendered image")
            size = target.stat().st_size
            if size > HTML_SINGLE_IMAGE_LIMIT or used + size > HTML_IMAGE_BUDGET:
                notes.append(f"{location}预览超出导出大小上限，未嵌入此文件；请回应用对照，或按章节拆分后导出。")
                continue
            with target.open("rb") as stream:
                content = stream.read(HTML_SINGLE_IMAGE_LIMIT + 1)
            size = len(content)
            if size > HTML_SINGLE_IMAGE_LIMIT or used + size > HTML_IMAGE_BUDGET:
                notes.append(f"{location}预览超出导出大小上限，未嵌入此文件；请回应用对照，或按章节拆分后导出。")
                continue
            if content.startswith(b"\x89PNG\r\n\x1a\n") and content.endswith(b"IEND\xaeB`\x82"):
                mime = "image/png"
            elif content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
                mime = "image/jpeg"
            elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                raise ValueError("not an image")
            used += size
            images[relative] = f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
        except (OSError, ValueError):
            notes.append(f"{location}的预览缺失或无法打包，未嵌入此文件；图示和公式仍待核对。")
    return images, list(dict.fromkeys(notes))


def _level(value: Any) -> str:
    return str(value) if value is not None else "—"


def export_markdown(project_dir: str | Path, output: str | Path | None = None) -> Path:
    project_dir = active_project_dir(project_dir)
    paths = project_paths(project_dir)
    if paths["study_guide"].exists():
        target = Path(output) if output else paths["exports"] / "study-guide.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(load_project_guide(project_dir)), encoding="utf-8")
        return target
    map_path = paths["lesson_map"]
    # Public fixtures often keep a hand-authored map at the project root;
    # accept that layout while generated projects continue using derived/.
    if not map_path.exists() and paths["root"].joinpath("lesson-map.json").exists():
        map_path = paths["root"] / "lesson-map.json"
    data = read_json(map_path)
    target = Path(output) if output else paths["exports"] / "lesson.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {data.get('subject', 'Study project')} lesson reconstruction",
        "",
        f"> Status: {data.get('notes', {}).get('status', 'unknown')}",
        "",
        "## Overview",
        "",
        f"- Pages/frames: {len(data.get('pages', []))}",
        f"- Speech segments: {len(data.get('audio_segments', []))}",
        f"- Knowledge units: {len(data.get('units', []))}",
        f"- Claims: {len(data.get('claims', []))}",
        "",
        "## Knowledge units",
        "",
    ]
    units = data.get("units", [])
    if not units:
        lines.append("No knowledge units have been reconstructed yet.")
    for unit in units:
        lines.extend(
            [
                f"### {unit.get('unit_id', 'unit')} — {unit.get('title', 'Untitled')}",
                "",
                unit.get("summary", ""),
                "",
                f"- Understanding: `{_level(unit.get('understanding_level'))}`",
                f"- Assessment evidence: `{_level(unit.get('exam_evidence_level'))}`",
                f"- Status: `{unit.get('status', 'unknown')}`",
                "",
            ]
        )
    lines.extend(["## Claims", ""])
    claims = data.get("claims", [])
    if not claims:
        lines.append("No claims have been added yet.")
    for claim in claims:
        labels = ", ".join(claim.get("source_labels", [])) or "source pending"
        lines.append(
            f"- **{claim.get('claim_id', 'claim')}** {claim.get('text', '')} "
            f"(U: `{_level(claim.get('understanding_level'))}`, "
            f"E: `{_level(claim.get('exam_evidence_level'))}`; {labels})"
        )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def export_study_guide(
    project_dir: str | Path,
    output: str | Path | None = None,
    *,
    format: str = "md",
) -> Path:
    """Export the learner-facing guide as Markdown, HTML, or JSON."""

    project_dir = active_project_dir(project_dir)
    guide = load_project_guide(project_dir)
    paths = project_paths(project_dir)
    suffix = {"md": ".md", "html": ".html", "json": ".json"}.get(format)
    if suffix is None:
        raise ValueError("format must be one of: md, html, json")
    target = Path(output) if output else paths["exports"] / f"study-guide{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if format == "md":
        target.write_text(render_markdown(guide), encoding="utf-8")
    elif format == "html":
        images, notes = guide_image_data(paths["root"], guide)
        target.write_text(render_html(guide, page_images=images, image_notes=notes), encoding="utf-8")
    else:
        target.write_text(guide.to_json() + "\n", encoding="utf-8")
    return target
