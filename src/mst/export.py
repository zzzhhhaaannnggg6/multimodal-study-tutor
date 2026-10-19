"""Human-readable exports for local study projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import project_paths, read_json
from .guide import load_project_guide, render_html, render_markdown


def _level(value: Any) -> str:
    return str(value) if value is not None else "—"


def export_markdown(project_dir: str | Path, output: str | Path | None = None) -> Path:
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
        target.write_text(render_html(guide), encoding="utf-8")
    else:
        target.write_text(guide.to_json() + "\n", encoding="utf-8")
    return target
