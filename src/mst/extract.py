"""Small, dependency-free extractors for common classroom inputs.

These extractors intentionally return text and stable locators only. They do
not infer teaching importance, align speech to slides, or manufacture quotes.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from math import cos, hypot, radians, sin
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from .multimodal import annotate_speech_metadata, visual_signals
from .models import SpeechSegment, VisualFrame

TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*[-–]+>\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)"
)
TAG_RE = re.compile(r"<[^>]+>")


def timestamp_seconds(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(text)


def parse_timestamped_text(path: str | Path) -> list[SpeechSegment]:
    """Parse VTT/SRT-like cues, preserving cue order and text."""

    source = Path(path)
    lines = source.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    segments: list[SpeechSegment] = []
    index = 0
    while index < len(lines):
        match = TIME_RANGE_RE.search(lines[index])
        if not match:
            index += 1
            continue
        text_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text = TAG_RE.sub("", lines[index]).strip()
            if text and not text.startswith("NOTE"):
                text_lines.append(text)
            index += 1
        start = timestamp_seconds(match.group("start"))
        end = timestamp_seconds(match.group("end"))
        segments.append(
            SpeechSegment(
                segment_id=f"{source.stem}::s{len(segments) + 1:04d}",
                source_id=source.stem,
                media_id=source.stem,
                start=start,
                end=end,
                text=" ".join(text_lines),
                transcript=" ".join(text_lines),
                status="pending",
                metadata=annotate_speech_metadata({}, " ".join(text_lines)),
            )
        )
        index += 1
    return segments


def extract_docx_transcript(path: str | Path) -> list[SpeechSegment]:
    """Group timestamp headers with their following speech paragraphs.

    Keep original paragraphs in metadata. The next marker is only an inferred
    cue boundary, not a measured end of speech; never infer across a clock reset.
    """

    source = Path(path)
    with zipfile.ZipFile(source) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[tuple[int, str]] = []
    for position, paragraph in enumerate(root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"), 1):
        text = "".join(
            node.text or ""
            for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        ).strip()
        if text:
            paragraphs.append((position, text))
    timestamp = re.compile(r"^\s*[\[【（(]?((?:\d{1,2}:)?[0-5]?\d:[0-5]\d(?:[.,]\d+)?)[\]】）)]?(?:\s*[|｜·•]\s*|\s+|$)")
    has_markers = any(timestamp.match(text) for _, text in paragraphs)
    cues: list[dict] = []
    current: dict | None = None
    block = 0
    for position, paragraph in paragraphs:
        match = timestamp.match(paragraph)
        if match:
            start = timestamp_seconds(match.group(1))
            if current and current["start"] is not None and start <= current["start"]:
                block += 1
            current = {"start": start, "texts": [], "raw": [], "positions": [], "block": block}
            cues.append(current)
            cleaned = paragraph[match.end():].strip()
        else:
            cleaned = paragraph
            if current is None:
                current = {"start": None, "texts": [], "raw": [], "positions": [], "block": block}
                cues.append(current)
        current["raw"].append(paragraph)
        current["positions"].append(position)
        if cleaned:
            current["texts"].append(cleaned)
    segments: list[SpeechSegment] = []
    for index, cue in enumerate(cues):
        start = cue["start"]
        cleaned = "\n".join(cue["texts"])
        export_header = bool(re.search(r"授课老师[：:]|课程名称[：:]|\d{4}[-/]\d{1,2}[-/]\d{1,2}", cleaned))
        administrative = not cleaned or (has_markers and start is None and export_header and len(cleaned) <= 160)
        following = cues[index + 1] if index + 1 < len(cues) else None
        end = following["start"] if (
            following and start is not None and following["start"] is not None
            and following["start"] > start and following["block"] == cue["block"]
        ) else None
        segments.append(
            SpeechSegment(
                segment_id=f"{source.stem}::s{index + 1:04d}",
                source_id=source.stem,
                media_id=source.stem,
                start=start,
                end=end,
                text=cleaned,
                kind="administrative" if administrative else "lecture",
                transcript=cleaned,
                status="pending",
                notes=(
                    "DOCX cue grouped; end is an inferred boundary at the next marker, not a measured speech end."
                    if end is not None
                    else "DOCX paragraph extracted; no reliable end timestamp was available."
                ),
                metadata={
                    **annotate_speech_metadata({}, cleaned),
                    "raw_transcript": "\n".join(cue["raw"]),
                    "paragraph_numbers": cue["positions"],
                    "timeline_block": cue["block"],
                    "end_inferred": end is not None,
                    "administrative": administrative,
                },
            )
        )
    return segments


def _pptx_diagram_graph(root: ElementTree.Element) -> tuple[list[str], list[str]]:
    """Read connectivity separately from arrow direction; all remain cues.

    Explicit endpoint IDs do not imply a direction. Geometric fallback is
    local and requires usable transforms for every containing group.
    """

    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    parents = {child: parent for parent in root.iter() for child in parent}

    def box_transform(xfrm):
        if xfrm is None:
            return None
        off, ext = xfrm.find(f"{a}off"), xfrm.find(f"{a}ext")
        if off is None or ext is None:
            return None
        try:
            x, y = float(off.get("x")), float(off.get("y"))
            w, h = float(ext.get("cx")), float(ext.get("cy"))
            angle = radians(float(xfrm.get("rot", "0")) / 60000)
        except (ValueError, TypeError):
            return None

        def point(u, v):
            dx = (u - 0.5) * w * (-1 if xfrm.get("flipH") in {"1", "true"} else 1)
            dy = (v - 0.5) * h * (-1 if xfrm.get("flipV") in {"1", "true"} else 1)
            return (x + w / 2 + dx * cos(angle) - dy * sin(angle),
                    y + h / 2 + dx * sin(angle) + dy * cos(angle))

        return point

    def geometry(element):
        property_tag = "grpSpPr" if element.tag == f"{p}grpSp" else "spPr"
        point = box_transform(element.find(f"./{p}{property_tag}/{a}xfrm"))
        if point is None:
            return None
        group_transforms = []
        ancestor = parents.get(element)
        while ancestor is not None:
            if ancestor.tag == f"{p}grpSp":
                xfrm = ancestor.find(f"./{p}grpSpPr/{a}xfrm")
                group_point = box_transform(xfrm)
                if group_point is None:
                    return None
                child_off, child_ext = xfrm.find(f"{a}chOff"), xfrm.find(f"{a}chExt")
                if child_off is None or child_ext is None:
                    return None
                try:
                    ox, oy = float(child_off.get("x")), float(child_off.get("y"))
                    sx, sy = float(child_ext.get("cx")), float(child_ext.get("cy"))
                    if sx <= 0 or sy <= 0:
                        return None
                except (ValueError, TypeError):
                    return None
                group_transforms.append((group_point, ox, oy, sx, sy))
            ancestor = parents.get(ancestor)

        def slide_point(u, v):
            x, y = point(u, v)
            for group_point, ox, oy, sx, sy in group_transforms:
                x, y = group_point((x - ox) / sx, (y - oy) / sy)
            return x, y

        corners = [slide_point(u, v) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))]
        bbox = (min(t[0] for t in corners), min(t[1] for t in corners),
                max(t[0] for t in corners), max(t[1] for t in corners))
        return slide_point, bbox
    def clean_label(value: str) -> str:
        compact = " ".join(value.split())
        return compact if len(compact) <= 120 else compact[:117].rstrip() + "…"

    def bbox_distance(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> float:
        x, y = point
        left, top, right, bottom = bbox
        dx = max(left - x, 0.0, x - right)
        dy = max(top - y, 0.0, y - bottom)
        return hypot(dx, dy)

    node_rows: dict[str, dict[str, object]] = {}
    arrow_shapes: list[dict[str, object]] = []
    for tag in ("sp", "graphicFrame", "pic"):
        for element in root.findall(f".//{p}{tag}"):
            props = element.find(f".//{p}cNvPr")
            node_id = props.get("id") if props is not None else None
            if not node_id:
                continue
            label = clean_label(" ".join(
                node.text.strip()
                for node in element.iter(f"{a}t")
                if node.text and node.text.strip()
            ))
            shape_geometry = geometry(element)
            preset_node = element.find(f".//{a}prstGeom")
            preset = preset_node.get("prst", "") if preset_node is not None else ""
            if tag == "sp" and preset.lower() in {"leftrightarrow", "updownarrow", "rightarrow", "leftarrow", "uparrow", "downarrow"}:
                if shape_geometry:
                    arrow_shapes.append({"preset": preset.lower(), "geometry": shape_geometry})
                continue  # The arrow's own label cannot be an endpoint node.
            if not label or label.isdigit():
                continue
            # Decorative boxes and their centered label are often grouped.
            # Use that group's extent only if it has exactly this one label.
            ancestor = parents.get(element)
            while ancestor is not None and ancestor.tag == f"{p}grpSp":
                group_label = clean_label(" ".join(t.text.strip() for t in ancestor.iter(f"{a}t") if t.text and t.text.strip()))
                group_geometry = geometry(ancestor)
                if group_label != label or group_geometry is None:
                    break
                shape_geometry = group_geometry
                ancestor = parents.get(ancestor)
            node_rows[str(node_id)] = {
                "label": label,
                "bbox": shape_geometry[1] if shape_geometry else None,
                "fallback": element.find(f".//{p}ph") is None and len(label) <= 60,
            }

    nodes = [str(row["label"]) for row in node_rows.values() if str(row["label"]).strip()]
    edges: list[str] = []
    def connector_direction(connector: ElementTree.Element) -> str:
        head = connector.find(f"./{p}spPr/{a}ln/{a}headEnd")
        tail = connector.find(f"./{p}spPr/{a}ln/{a}tailEnd")
        at_start = head is not None and head.get("type") not in {None, "none"}
        at_end = tail is not None and tail.get("type") not in {None, "none"}
        return "↔" if at_start and at_end else "←" if at_start else "→" if at_end else "—"

    def nearest(point, length, excluded=None):
        candidates = []
        for node_id, row in node_rows.items():
            bbox = row["bbox"]
            if node_id == excluded or bbox is None or not row["fallback"]:
                continue
            size = min(bbox[2] - bbox[0], bbox[3] - bbox[1])
            distance = bbox_distance(point, bbox)
            if distance <= min(length * 0.25, size * 0.5):
                candidates.append((distance, node_id))
        candidates.sort()
        if not candidates or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < max(1e-6, length * 0.02)):
            return None
        return candidates[0][1]

    for connector in root.findall(f".//{p}cxnSp"):
        start = connector.find(f".//{a}stCxn")
        end = connector.find(f".//{a}endCxn")
        start_id = start.get("id") if start is not None else None
        end_id = end.get("id") if end is not None else None
        connector_geometry = geometry(connector)
        if connector_geometry:
            point, _ = connector_geometry
            first, last = point(0, 0), point(1, 1)
            length = hypot(last[0] - first[0], last[1] - first[1])
            if start_id not in node_rows:
                start_id = nearest(first, length, end_id)
            if end_id not in node_rows:
                end_id = nearest(last, length, start_id)
        if start_id in node_rows and end_id in node_rows and start_id != end_id:
            edges.append(f"{node_rows[start_id]['label']} {connector_direction(connector)} {node_rows[end_id]['label']}")

    # Preset arrows carry direction in their geometry, including rotation and
    # flips. Only attach labels close to both ends; do not guess across a slide.
    for arrow in arrow_shapes:
        preset = str(arrow["preset"])
        point, _ = arrow["geometry"]
        vertical = preset in {"uparrow", "downarrow", "updownarrow"}
        first, last = (point(0.5, 0), point(0.5, 1)) if vertical else (point(0, 0.5), point(1, 0.5))
        length = hypot(last[0] - first[0], last[1] - first[1])
        start_id = nearest(first, length)
        end_id = nearest(last, length, start_id)
        direction = "↔" if preset in {"leftrightarrow", "updownarrow"} else "←" if preset in {"leftarrow", "uparrow"} else "→"
        if start_id and end_id and start_id != end_id:
            edges.append(f"{node_rows[start_id]['label']} {direction} {node_rows[end_id]['label']}")
    return nodes, _unique_graph_edges(edges)


def _unique_graph_edges(edges: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        edge = str(edge).strip()
        if edge and edge not in seen:
            result.append(edge)
            seen.add(edge)
    return result


def _pptx_text(root: ElementTree.Element) -> str:
    """Preserve paragraph boundaries and explicit run super/subscripts."""
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    paragraphs = []
    parents = {child: parent for parent in root.iter() for child in parent}
    for paragraph in root.iter(f"{a}p"):
        ancestor = parents.get(paragraph)
        while ancestor is not None and not ancestor.tag.endswith("}sp"):
            ancestor = parents.get(ancestor)
        if ancestor is not None and ancestor.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}ph[@type='sldNum']") is not None:
            continue
        parts = []
        defaults = paragraph.find(f"./{a}pPr/{a}defRPr")
        for run in paragraph:
            if run.tag == f"{a}br":
                parts.append("\n")
                continue
            text = "".join(t.text or "" for t in run.iter(f"{a}t"))
            if not text:
                continue
            props = run.find(f"{a}rPr")
            baseline = props.get("baseline") if props is not None else None
            if baseline is None and defaults is not None:
                baseline = defaults.get("baseline")
            try:
                offset = int(baseline or 0)
            except ValueError:
                offset = 0
            if offset:
                text = ("^" if offset > 0 else "_") + "{" + text + "}"
            parts.append(text)
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_pptx_pages(path: str | Path) -> list[VisualFrame]:
    """Extract visible text from a PPTX without requiring python-pptx."""

    source = Path(path)
    pages: list[VisualFrame] = []
    drawing_namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    presentation_namespace = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    with zipfile.ZipFile(source) as archive:
        slide_names = sorted(
            (
                name for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
        )
        for page_number, name in enumerate(slide_names, 1):
            root = ElementTree.fromstring(archive.read(name))
            text = _pptx_text(root)
            shape_counts = {
                "shape": len(root.findall(f".//{presentation_namespace}sp")),
                "picture": len(root.findall(f".//{presentation_namespace}pic")),
                "connector": len(root.findall(f".//{presentation_namespace}cxnSp")),
                "graphic_frame": len(root.findall(f".//{presentation_namespace}graphicFrame")),
            }
            # A connector can be represented by a line shape in exported
            # decks, so inspect drawing geometry as an additional cue.
            line_count = len(root.findall(f".//{drawing_namespace}prstGeom[@prst='line']"))
            shape_counts["line"] = line_count
            diagram_nodes, diagram_edges = _pptx_diagram_graph(root)
            signals = visual_signals(
                text,
                shape_counts=shape_counts,
                image_count=shape_counts["picture"],
                connector_count=shape_counts["connector"] + line_count,
                diagram_nodes=diagram_nodes,
                diagram_edges=diagram_edges,
            )
            domain = signals.get("domain_signals", {})
            title = next((line for line in text.splitlines() if not line.strip().isdigit()), f"Slide {page_number}")
            pages.append(
                VisualFrame(
                    visual_id=f"{source.stem}::p{page_number:03d}",
                    source_id=source.stem,
                    page=page_number,
                    source_page=page_number,
                    title=title[:120],
                    text=text,
                    # Text extraction covers the reading channel.  A separate
                    # visual-review flag records diagrams/screenshots that
                    # still need image inspection.
                    status="covered" if text else "unresolved",
                    visual_kind=signals["kind"],
                    visual_summary=signals["summary"],
                    visual_evidence=[
                        *signals["code_lines"][:3],
                        *signals["formula_candidates"][:3],
                        *signals["diagram_keywords"][:5],
                        *signals["diagram_edges"][:3],
                        *domain.get("instruction_tokens", [])[:3],
                        *domain.get("datapath_stages", [])[:5],
                    ],
                    needs_visual_review=signals["review_required"],
                    metadata={"visual_analysis": signals},
                )
            )
    return pages


def extract_pdf_pages(path: str | Path) -> list[VisualFrame]:
    """Extract text pages from PDF when pypdf or pdftotext is available."""

    source = Path(path)
    texts: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore

        texts = [(page.extract_text() or "").strip() for page in PdfReader(str(source)).pages]
    except ImportError:
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(source), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return []
        texts = [item.strip() for item in result.stdout.split("\f")]
    pages: list[VisualFrame] = []
    for number, text in enumerate(texts, 1):
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), f"Page {number}")
        signals = visual_signals(text)
        domain = signals.get("domain_signals", {})
        pages.append(
            VisualFrame(
                visual_id=f"{source.stem}::p{number:03d}",
                source_id=source.stem,
                page=number,
                title=first_line[:120],
                text=text,
                status="covered" if text else "unresolved",
                notes="PDF text extracted; figures and scanned text may require visual/OCR review.",
                visual_kind=signals["kind"],
                visual_summary=signals["summary"],
                visual_evidence=[
                    *signals["formula_candidates"][:3],
                    *signals["code_lines"][:3],
                    *domain.get("instruction_tokens", [])[:3],
                    *domain.get("datapath_stages", [])[:5],
                ],
                needs_visual_review=True if signals["review_required"] else not bool(text.strip()),
                metadata={"visual_analysis": signals},
            )
        )
    return pages


def extract_markdown_pages(path: str | Path) -> list[VisualFrame]:
    """Treat Markdown headings as lightweight reading frames."""

    source = Path(path)
    rows = source.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: list[VisualFrame] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_title is None and not current_lines:
            return
        number = len(frames) + 1
        text = " ".join(current_lines).strip()
        signals = visual_signals(text)
        domain = signals.get("domain_signals", {})
        frames.append(
            VisualFrame(
                visual_id=f"{source.stem}::p{number:03d}",
                source_id=source.stem,
                page=number,
                title=current_title or f"Section {number}",
                text=text,
                status="covered" if text else "unresolved",
                visual_kind=signals["kind"],
                visual_summary=signals["summary"],
                visual_evidence=[
                    *signals["formula_candidates"][:3],
                    *signals["code_lines"][:3],
                    *domain.get("instruction_tokens", [])[:3],
                    *domain.get("datapath_stages", [])[:5],
                ],
                needs_visual_review=signals["review_required"],
                metadata={"visual_analysis": signals},
            )
        )

    for row in rows:
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", row)
        if heading:
            flush()
            current_title = heading.group(1)
            current_lines = []
        elif row.strip():
            current_lines.append(row.strip())
    flush()
    return frames


def extract_source(path: str | Path, kind: str | None = None) -> tuple[list[VisualFrame], list[SpeechSegment]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".docx":
        return [], extract_docx_transcript(source)
    if suffix == ".txt":
        text = source.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not text:
            return [], []
        return [], [
            SpeechSegment(
                segment_id=f"{source.stem}::s0001",
                source_id=source.stem,
                media_id=source.stem,
                text=text,
                transcript=text,
                status="pending",
                notes="普通转写没有可靠时间戳；不能据此声称精确教师强调。",
                metadata=annotate_speech_metadata({}, text),
            )
        ]
    if kind == "transcript" or suffix in {".srt", ".vtt"}:
        return [], parse_timestamped_text(source)
    if suffix == ".pptx":
        return extract_pptx_pages(source), []
    if suffix == ".pdf":
        return extract_pdf_pages(source), []
    if suffix in {".md", ".markdown"}:
        return extract_markdown_pages(source), []
    return [], []


def extract_manifest_sources(rows: Iterable[dict[str, object]]) -> tuple[list[VisualFrame], list[SpeechSegment]]:
    pages: list[VisualFrame] = []
    segments: list[SpeechSegment] = []
    for row in rows:
        path = row.get("path")
        if not path:
            continue
        try:
            visual, speech = extract_source(path, str(row.get("kind", "")))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
            # Keep ingestion resilient; the source remains in the manifest and
            # a later validation/review step can surface the parser issue.
            continue
        source_id = str(row.get("source_id", ""))
        for item in visual:
            item.source_id = source_id or item.source_id
        for item in speech:
            item.source_id = source_id or item.source_id
        pages.extend(visual)
        segments.extend(speech)
    return pages, segments
