"""Small, dependency-free extractors for common classroom inputs.

These extractors intentionally return text and stable locators only. They do
not infer teaching importance, align speech to slides, or manufacture quotes.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

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
            )
        )
    return segments


def extract_pptx_pages(path: str | Path) -> list[VisualFrame]:
    """Extract visible text from a PPTX without requiring python-pptx."""

    source = Path(path)
    pages: list[VisualFrame] = []
    namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
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
            title = text.split(" ", 1)[0] if text else f"Slide {page_number}"
            pages.append(
                VisualFrame(
                    visual_id=f"{source.stem}::p{page_number:03d}",
                    source_id=source.stem,
                    page=page_number,
                    source_page=page_number,
                    title=title[:120],
                    text=text,
                    status="pending",
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
        frames.append(
            VisualFrame(
                visual_id=f"{source.stem}::p{number:03d}",
                source_id=source.stem,
                page=number,
                title=current_title or f"Section {number}",
                text=text,
                status="pending",
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
    if kind == "transcript" or suffix in {".srt", ".vtt"}:
        return [], parse_timestamped_text(source)
    if suffix == ".pptx":
        return extract_pptx_pages(source), []
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
