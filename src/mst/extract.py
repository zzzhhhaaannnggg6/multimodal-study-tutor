"""Small, dependency-free extractors for common classroom inputs.

These extractors intentionally return text and stable locators only. They do
not infer teaching importance, align speech to slides, or manufacture quotes.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from math import hypot
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
    """Extract paragraph text from a DOCX transcript without OCR.

    Timestamp tokens such as ``00:12`` or ``00:01:12`` are retained as cue
    starts when present. DOCX screenshots and drawings are deliberately not
    treated as speech; a later media extractor can add them as visual frames.
    """

    source = Path(path)
    with zipfile.ZipFile(source) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(
            node.text or ""
            for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        ).strip()
        if text:
            paragraphs.append(text)
    timestamp = re.compile(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")
    segments: list[SpeechSegment] = []
    for paragraph in paragraphs:
        match = timestamp.search(paragraph)
        start = timestamp_seconds(match.group(1)) if match else None
        segments.append(
            SpeechSegment(
                segment_id=f"{source.stem}::s{len(segments) + 1:04d}",
                source_id=source.stem,
                media_id=source.stem,
                start=start,
                text=paragraph,
                transcript=paragraph,
                status="pending",
                notes="DOCX paragraph extracted; timestamp/end alignment requires review.",
                metadata=annotate_speech_metadata({}, paragraph),
            )
        )
    return segments


def _pptx_diagram_graph(root: ElementTree.Element) -> tuple[list[str], list[str]]:
    """Read labelled PPTX nodes and connector endpoints when present.

    PowerPoint stores connector endpoint IDs in ``a:stCxn``/``a:endCxn``.
    When an exporter omits those IDs, the fallback uses the nearest two shape
    centres and marks the result as an undirected candidate in the text.  It is
    intentionally a review cue rather than a verified diagram interpretation.
    """

    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    node_rows: dict[str, dict[str, object]] = {}
    for tag in ("sp", "graphicFrame", "pic"):
        for element in root.findall(f".//{p}{tag}"):
            props = element.find(f".//{p}cNvPr")
            node_id = props.get("id") if props is not None else None
            if not node_id:
                continue
            label = " ".join(
                node.text.strip()
                for node in element.iter(f"{a}t")
                if node.text and node.text.strip()
            )
            xfrm = element.find(f".//{a}xfrm")
            off = xfrm.find(f"{a}off") if xfrm is not None else None
            ext = xfrm.find(f"{a}ext") if xfrm is not None else None
            try:
                x = float(off.get("x", "0")) if off is not None else 0.0
                y = float(off.get("y", "0")) if off is not None else 0.0
                cx = float(ext.get("cx", "0")) if ext is not None else 0.0
                cy = float(ext.get("cy", "0")) if ext is not None else 0.0
            except (TypeError, ValueError):
                x = y = cx = cy = 0.0
            node_rows[str(node_id)] = {
                "label": label or f"节点 {node_id}",
                "center": (x + cx / 2.0, y + cy / 2.0),
            }

    nodes = [str(row["label"]) for row in node_rows.values() if str(row["label"]).strip()]
    edges: list[str] = []
    for connector in root.findall(f".//{p}cxnSp"):
        start = connector.find(f".//{a}stCxn")
        end = connector.find(f".//{a}endCxn")
        start_id = start.get("id") if start is not None else None
        end_id = end.get("id") if end is not None else None
        if start_id in node_rows and end_id in node_rows:
            edges.append(f"{node_rows[start_id]['label']} → {node_rows[end_id]['label']}")
            continue
        xfrm = connector.find(f".//{a}xfrm")
        off = xfrm.find(f"{a}off") if xfrm is not None else None
        ext = xfrm.find(f"{a}ext") if xfrm is not None else None
        try:
            center = (
                float(off.get("x", "0")) + (float(ext.get("cx", "0")) if ext is not None else 0.0) / 2.0,
                float(off.get("y", "0")) + (float(ext.get("cy", "0")) if ext is not None else 0.0) / 2.0,
            )
        except (TypeError, ValueError):
            center = (0.0, 0.0)
        nearest = sorted(
            (
                (hypot(center[0] - row["center"][0], center[1] - row["center"][1]), row["label"])
                for row in node_rows.values()
            ),
            key=lambda item: item[0],
        )[:2]
        if len(nearest) == 2:
            edges.append(f"{nearest[0][1]} ↔ {nearest[1][1]}")
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


def extract_pptx_pages(path: str | Path) -> list[VisualFrame]:
    """Extract visible text from a PPTX without requiring python-pptx."""

    source = Path(path)
    pages: list[VisualFrame] = []
    namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
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
            text = " ".join(
                node.text.strip()
                for node in root.iter(f"{namespace}t")
                if node.text and node.text.strip()
            )
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
            title = text.split(" ", 1)[0] if text else f"Slide {page_number}"
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
