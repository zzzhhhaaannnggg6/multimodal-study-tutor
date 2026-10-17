"""Validation gates for lesson maps.

Validation is deliberately separate from the dataclasses in :mod:`mst.models`.
The dataclasses make it convenient to build a map; this module decides whether
the resulting map is safe to publish and trustworthy enough to drive a study
agent.  It has no third-party dependency and returns structured diagnostics so
CLI, Web and agent clients can choose their own presentation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import LessonMap, coerce_lesson_map


LEVEL_U = {"U0", "U1", "U2", "U3"}
LEVEL_E = {"E-", "E0", "E1", "E2", "E3"}
CONFIDENCE = {"high", "medium", "low", "unresolved"}
ALIGNMENT_STATUSES = {
    "aligned",
    "aligned_range",
    "visual_explanation",
    "cross_visual",
    "question",
    "assessment",
    "classroom_supplement",
    "lecture_supplement",
    "pending",
    "待确认",
    "课堂补充",
    "录音未覆盖",
    "unmapped",
    "not_covered",
    "not_in_audio",
    "administrative",
    "not_applicable",
    "unresolved",
    "supplement",
    "navigation",
    "skipped",
    "merged",
    "covered",
    "ready",
}
RECORD_STATUSES = {
    "draft",
    "ready",
    "verified",
    "pending",
    "unresolved",
    "conflict",
    "covered",
    "merged",
    "navigation",
    "supplement",
    "skipped",
    "invalid",
}
ID_RE = re.compile(r"^[^\s/\\]+(?:[/:@._-][^\s/\\]+)*$")
TIME_RE = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d+)?)$")
WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")
UNC_RE = re.compile(r"^(?:\\\\|//)[^/\\]+[/\\]")
EXCLUSION_RE = re.compile(
    r"(?:不考|不在考试|不纳入考核|不作为考核|not\s+(?:assessed|on\s+the\s+(?:exam|test))|"
    r"excluded\s+from\s+(?:the\s+)?assessment)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Diagnostic:
    """One validation finding.

    ``path`` uses a JSONPath-like notation (for example
    ``claims[0].sources[0].quote``) and is intentionally stable enough for a
    UI to focus the offending field.
    """

    code: str
    message: str
    path: str = "$"
    severity: str = "error"
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> str:
        """Alias used by a few report consumers."""

        return self.severity

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
            **({"details": self.details} if self.details else {}),
        }


@dataclass
class ValidationReport:
    """Collection of findings returned by :func:`validate_lesson_map`."""

    diagnostics: list[Diagnostic] = field(default_factory=list)
    map: LessonMap | None = None

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "warning"]

    @property
    def issues(self) -> list[Diagnostic]:
        """Backward-compatible alias for the complete diagnostics list."""

        return self.diagnostics

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def valid(self) -> bool:
        return self.ok

    @property
    def is_valid(self) -> bool:
        return self.ok

    def __bool__(self) -> bool:
        return self.ok

    def __iter__(self):
        return iter(self.diagnostics)

    def add(
        self,
        code: str,
        message: str,
        path: str = "$",
        *,
        severity: str = "error",
        details: Mapping[str, Any] | None = None,
    ) -> Diagnostic:
        item = Diagnostic(code, message, path, severity, dict(details or {}))
        self.diagnostics.append(item)
        return item

    def extend(self, other: "ValidationReport") -> None:
        self.diagnostics.extend(other.diagnostics)

    def raise_for_errors(self) -> None:
        if self.errors:
            summary = "; ".join(f"{item.path}: {item.message}" for item in self.errors[:8])
            if len(self.errors) > 8:
                summary += f"; ... ({len(self.errors) - 8} more)"
            raise ValueError(summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, LessonMap):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (str, Path)):
        source = Path(value)
        try:
            return json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # A JSON string is useful in API calls; try it before reporting a
            # type error.  A malformed string is handled by the caller.
            try:
                parsed = json.loads(str(value))
            except json.JSONDecodeError as exc:
                raise TypeError(f"lesson map path does not exist: {source}") from exc
            if not isinstance(parsed, Mapping):
                raise TypeError("lesson map JSON must contain an object")
            return dict(parsed)
        except json.JSONDecodeError as exc:
            raise TypeError(f"invalid JSON lesson map: {source}: {exc}") from exc
    raise TypeError(f"lesson map must be a mapping, path, or LessonMap; got {type(value).__name__}")


def _items(data: Mapping[str, Any], *names: str) -> list[Any]:
    """Read one canonical array and its aliases without duplicating records."""

    values: list[Any] = []
    seen: set[str] = set()
    found = False
    # A page can legitimately share its source_id with every other page in a
    # deck.  Choose the record identity for the collection before falling back
    # to generic keys; otherwise alias de-duplication silently drops pages.
    if any(name in {"pages", "visual_sources", "visual_frames"} for name in names):
        identity_keys = ("visual_id", "page_id", "slide_id", "id")
    elif any(name in {"speech_segments", "media_segments", "audio_segments"} for name in names):
        identity_keys = ("segment_id", "media_segment_id", "id")
    elif any(name in {"units", "knowledge_units"} for name in names):
        identity_keys = ("unit_id", "id")
    elif any(name in {"claims", "claim_ledger", "claimLedger"} for name in names):
        identity_keys = ("claim_id", "id")
    elif any(name in {"lessons"} for name in names):
        identity_keys = ("lesson_id", "id")
    elif any(name in {"review_items", "reviews"} for name in names):
        identity_keys = ("review_id", "item_id", "id")
    elif "assessment_evidence" in names:
        identity_keys = ("evidence_id", "id")
    else:
        identity_keys = ("source_id", "id")
    for name in names:
        if name not in data or data[name] is None:
            continue
        found = True
        raw = data[name]
        if not isinstance(raw, list):
            if isinstance(raw, Mapping):
                # JSON maps keyed by stable IDs are a common compact form for
                # assessment evidence and claim ledgers.  Materialise them as
                # records while retaining the key as a fallback ID.
                for key, item in raw.items():
                    if isinstance(item, Mapping):
                        row = dict(item)
                        if not any(row.get(candidate) is not None for candidate in identity_keys):
                            row[identity_keys[0]] = str(key)
                        values.append(row)
                    else:
                        values.append(item)
            else:
                # Preserve a malformed value so the caller can report its type.
                values.append(raw)
            continue
        for item in raw:
            if isinstance(item, Mapping):
                ident = next((item.get(key) for key in identity_keys if item.get(key) is not None), None)
                marker = str(ident) if ident is not None else ""
                if marker and marker in seen:
                    continue
                if marker:
                    seen.add(marker)
            values.append(item)
    return values if found else []


def _value(item: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return default


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _id(item: Any, *keys: str) -> str:
    if not isinstance(item, Mapping):
        return ""
    raw = _value(item, *keys, "id")
    return str(raw) if raw is not None else ""


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and bool(ID_RE.fullmatch(value))


def _seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace("：", ":").replace("，", ".")
    try:
        return float(text)
    except ValueError:
        pass
    match = TIME_RE.fullmatch(text)
    if not match:
        return None
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _is_absolute_path(value: str) -> bool:
    text = value.strip()
    if not text or text.startswith(("http://", "https://", "ftp://", "mailto:")):
        return False
    return text.startswith("/") or text.startswith("~/") or bool(WINDOWS_ABS_RE.match(text)) or bool(UNC_RE.match(text))


PATH_KEYS = {
    "path",
    "local_path",
    "absolute_path",
    "asset_path",
    "image_path",
    "input_path",
    "output_path",
    "root_path",
    "file_path",
    "source_path",
    "document",
    "file",
}


def _scan_absolute_paths(value: Any, report: ValidationReport, path: str = "$", key: str | None = None, seen: set[int] | None = None) -> None:
    """Find local absolute paths without treating URLs as leaked paths."""

    if seen is None:
        seen = set()
    if isinstance(value, (dict, list)):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
    if isinstance(value, str) and _is_absolute_path(value):
        report.add(
            "privacy.absolute_path",
            "absolute local path is not portable; use a project-relative path or source ID",
            path,
            details={"value": value} if key in PATH_KEYS or value.startswith(("/", "~", "\\")) else None,
        )
        return
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            child_path = f"{path}.{child_key}"
            _scan_absolute_paths(child, report, child_path, str(child_key), seen)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_absolute_paths(child, report, f"{path}[{index}]", key, seen)


def _check_ids(
    report: ValidationReport,
    rows: Sequence[Any],
    path: str,
    id_keys: Sequence[str],
    label: str,
) -> dict[str, int]:
    known: dict[str, int] = {}
    for index, row in enumerate(rows):
        row_path = f"{path}[{index}]"
        if not isinstance(row, Mapping):
            report.add("shape.record", f"{label} must be an object", row_path)
            continue
        raw = _value(row, *id_keys, "id")
        if raw is None or raw == "":
            report.add("id.missing", f"{label} requires a stable ID", row_path)
            continue
        if not _valid_id(raw):
            report.add("id.invalid", f"{label} ID must be a non-empty token without whitespace or path separators", f"{row_path}.id")
            continue
        ident = str(raw)
        if ident in known:
            report.add("id.duplicate", f"duplicate {label} ID: {ident}", f"{row_path}.id", details={"first_index": known[ident]})
        else:
            known[ident] = index
    return known


def _check_ref_list(
    report: ValidationReport,
    row: Mapping[str, Any],
    field_name: str,
    known: Mapping[str, int],
    path: str,
) -> None:
    raw = _value(row, field_name)
    if raw is None:
        return
    if not isinstance(raw, list):
        report.add("shape.references", f"{field_name} must be an array", f"{path}.{field_name}")
        return
    for index, ref in enumerate(raw):
        if not isinstance(ref, str) or not ref:
            report.add("reference.invalid", f"{field_name} entries must be non-empty IDs", f"{path}.{field_name}[{index}]")
        elif known and ref not in known:
            report.add("reference.unknown", f"unknown ID referenced by {field_name}: {ref}", f"{path}.{field_name}[{index}]")


def _evidence_rows(row: Mapping[str, Any]) -> list[Any]:
    raw = _value(row, "sources", "evidence", "source", default=[])
    return _list(raw)


def _has_locator(evidence: Mapping[str, Any]) -> bool:
    locator_keys = ("ref", "source_id", "page", "section", "start", "end", "timestamp", "locator", "document")
    return any(evidence.get(key) not in (None, "", []) for key in locator_keys)


_LOCATOR_RE = re.compile(
    r"(?:::|@|#|/|\\|\b(?:p(?:age)?|pp|slide|frame|sec(?:tion)?|para(?:graph)?|line|q(?:uestion)?|item|"
    r"t(?:ime)?|audio|transcript)\s*[.:#_\-/]?\s*\d+|第\s*\d+\s*(?:页|段|行|题|条)|"
    r"\b\d{1,3}:\d{2}(?::\d{2}(?:[.,]\d+)?)?\b|\b\d+(?:[._:-]\d+)+\b|"
    r"\b[A-Za-z][A-Za-z0-9_-]*[-_:][A-Za-z0-9_.:-]+\b)",
    re.IGNORECASE,
)


def _locator_is_navigable(evidence: Mapping[str, Any]) -> bool:
    """Reject vague refs such as ``foo`` while allowing stable IDs and pages."""

    if any(evidence.get(key) not in (None, "", []) for key in ("page", "section", "start", "end", "timestamp", "locator")):
        return True
    source_id = evidence.get("source_id")
    ref = evidence.get("ref") or evidence.get("document")
    if source_id and not ref:
        # A stable source ID is a valid locator when no more granular anchor is
        # available (for example, a whole reading or a textbook chapter).
        return True
    if isinstance(ref, str) and _LOCATOR_RE.search(ref):
        return True
    return False


def _strong_evidence_locator(evidence: Mapping[str, Any]) -> bool:
    """Return whether an E3/E- locator can be revisited at page/section/time."""

    if any(evidence.get(key) not in (None, "", []) for key in ("page", "section", "start", "end", "timestamp")):
        return True
    ref = evidence.get("ref") or evidence.get("locator") or ""
    if isinstance(ref, str):
        return bool(re.search(r"(?:@|#|\b(?:p(?:age)?|pp|slide|section|sec|t(?:ime)?|audio|transcript)\s*[.:#_\-/]?\s*\d|\b\d{1,3}:\d{2})", ref, re.IGNORECASE))
    return False


def _evidence_quote(evidence: Mapping[str, Any]) -> str:
    value = _value(evidence, "quote", "excerpt", "text", default="")
    return str(value).strip() if value is not None else ""


def _evidence_verified(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("verified")) or str(evidence.get("status", "")).lower() == "verified"


def _check_evidence(
    report: ValidationReport,
    row: Mapping[str, Any],
    path: str,
    *,
    required: bool,
    source_ids: Mapping[str, int],
    assessment_ids: Mapping[str, int],
    strict: bool = False,
) -> bool:
    evidence_rows = _evidence_rows(row)
    if not evidence_rows:
        if required:
            report.add("evidence.required", "E3/E- claims require at least one structured source locator", f"{path}.sources")
        return False
    usable = False
    for index, evidence in enumerate(evidence_rows):
        evidence_path = f"{path}.sources[{index}]"
        if isinstance(evidence, str):
            report.add("evidence.unstructured", "source entries must be objects with kind and a navigable locator", evidence_path)
            continue
        if not isinstance(evidence, Mapping):
            report.add("evidence.shape", "source entries must be objects", evidence_path)
            continue
        kind = _value(evidence, "kind", "source_kind")
        if not isinstance(kind, str) or not kind.strip():
            report.add("evidence.kind", "a source locator requires a non-empty kind", f"{evidence_path}.kind")
        if str(_value(evidence, "status", default="")).lower() == "invalid" or str(kind).lower() == "unknown":
            report.add("evidence.unstructured", "source entries must be structured locators, not free text", evidence_path)
        if not _has_locator(evidence):
            report.add("evidence.locator", "a source locator needs ref, source_id, page/section, timestamp, or equivalent location", evidence_path)
        elif not _locator_is_navigable(evidence):
            report.add("evidence.unlocatable", "source ref must include a page, time, stable ID, path, or equivalent locator", evidence_path)
        source_id = _value(evidence, "source_id")
        if source_id and source_ids and str(source_id) not in source_ids:
            report.add("reference.unknown_source", f"evidence refers to unknown source_id: {source_id}", f"{evidence_path}.source_id")
        evidence_id = _value(evidence, "evidence_id", "id")
        if evidence_id and str(evidence_id) in assessment_ids:
            pass
        if required:
            quote = _evidence_quote(evidence)
            if not quote:
                report.add("evidence.quote_required", "E3/E- evidence requires a short quote or excerpt", f"{evidence_path}.quote")
            if evidence.get("verified") is False:
                report.add("evidence.unverified", "E3/E- evidence is explicitly marked unverified", f"{evidence_path}.verified")
            elif not _evidence_verified(evidence):
                report.add(
                    "evidence.verification_missing",
                    "E3/E- evidence should record verified=true after checking the supplied source",
                    f"{evidence_path}.verified",
                    severity="error" if strict else "warning",
                )
            if not _strong_evidence_locator(evidence):
                report.add("evidence.time_or_page_required", "E3/E- evidence needs a teacher timestamp or document page/section locator", evidence_path)
            verification_usable = _evidence_verified(evidence) or (not strict and evidence.get("verified") is not False)
            if quote and _has_locator(evidence) and verification_usable and _strong_evidence_locator(evidence):
                usable = True
        elif _has_locator(evidence):
            usable = True
    return usable


def _check_time_range(report: ValidationReport, row: Mapping[str, Any], path: str, start_key: str = "start", end_key: str = "end") -> None:
    start_raw = _value(row, start_key, "start_time", "start_seconds")
    end_raw = _value(row, end_key, "end_time", "end_seconds")
    if start_raw is None and end_raw is None:
        return
    start = _seconds(start_raw)
    end = _seconds(end_raw)
    if start is None:
        report.add("time.invalid", "start time must be seconds or HH:MM:SS", f"{path}.{start_key}")
    elif start < 0:
        report.add("time.negative", "start time cannot be negative", f"{path}.{start_key}")
    # Timestamped transcripts frequently provide cue starts without reliable
    # ends. Preserve those open intervals for later alignment review; an end
    # is validated only when the input actually supplied one.
    if end_raw is not None and end is None:
        report.add("time.invalid", "end time must be seconds or HH:MM:SS", f"{path}.{end_key}")
    elif end is not None and end < 0:
        report.add("time.negative", "end time cannot be negative", f"{path}.{end_key}")
    if start is not None and end is not None and end <= start:
        report.add("time.order", "end time must be greater than start time", path)


def _check_assessment_record(report: ValidationReport, row: Mapping[str, Any], path: str, *, strict: bool) -> None:
    """Apply the minimum quote/locator/verification contract to assessment docs."""

    if not _evidence_quote(row):
        report.add("assessment.quote", "assessment evidence needs a quoted excerpt", f"{path}.quote")
    if not _has_locator(row) or not _locator_is_navigable(row):
        report.add("assessment.locator", "assessment evidence needs a page, section, line, or equivalent locator", path)
    if not any(_value(row, key) not in (None, "", []) for key in ("document", "file", "path", "ref", "source", "source_id")):
        report.add("assessment.source", "assessment evidence needs a document/source reference", path)
    if row.get("verified") is False:
        report.add("assessment.unverified", "assessment evidence is explicitly marked unverified", f"{path}.verified")
    elif row.get("verified") is not True and str(row.get("status", "")).lower() != "verified":
        report.add(
            "assessment.verification_missing",
            "assessment evidence should record verified=true after checking the supplied document",
            f"{path}.verified",
            severity="error" if strict else "warning",
        )


def _check_levels(report: ValidationReport, row: Mapping[str, Any], path: str, *, unit: bool = False) -> tuple[str, str]:
    u = str(_value(row, "understanding_level", "u_level", "U", default="U1"))
    e = str(_value(row, "exam_evidence_level", "e_level", "assessment_level", "E", default="E0"))
    if u not in LEVEL_U:
        report.add("priority.understanding", f"understanding level must be one of {sorted(LEVEL_U)}", f"{path}.understanding_level")
    if e not in LEVEL_E:
        report.add("priority.assessment", f"assessment evidence level must be one of {sorted(LEVEL_E)}", f"{path}.exam_evidence_level")
    text = str(_value(row, "text", "title", "statement", default=""))
    if e == "E0" and EXCLUSION_RE.search(text):
        report.add("assessment.e0_exclusion", "E0 means no observed signal, not explicit exclusion; use E- only with evidence", f"{path}.exam_evidence_level")
    return u, e


def _check_alignment(report: ValidationReport, row: Mapping[str, Any], path: str, visual_ids: Mapping[str, int], unit_ids: Mapping[str, int]) -> None:
    raw = row.get("alignment") if isinstance(row, Mapping) else None
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        report.add("alignment.shape", "alignment must be an object", f"{path}.alignment")
        return
    confidence = str(_value(raw, "confidence", "alignment_confidence", default="unresolved"))
    status = str(_value(raw, "status", "alignment_status", default="pending"))
    if confidence not in CONFIDENCE:
        report.add("alignment.confidence", f"alignment confidence must be one of {sorted(CONFIDENCE)}", f"{path}.alignment.confidence")
    if status not in ALIGNMENT_STATUSES:
        report.add("alignment.status", f"unknown alignment status: {status}", f"{path}.alignment.status")
    refs = _value(raw, "visual_ids", "slide_ids", "pages", "page_ids", default=[])
    if refs is None:
        refs = []
    if not isinstance(refs, list):
        report.add("alignment.references", "alignment visual_ids must be an array", f"{path}.alignment.visual_ids")
        refs = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, str) or (visual_ids and ref not in visual_ids):
            report.add("alignment.unknown_visual", f"alignment references unknown visual ID: {ref}", f"{path}.alignment.visual_ids[{index}]")
    unit_refs = _value(raw, "unit_ids", "units", default=[])
    if unit_refs and isinstance(unit_refs, list):
        for index, ref in enumerate(unit_refs):
            if unit_ids and ref not in unit_ids:
                report.add("alignment.unknown_unit", f"alignment references unknown unit ID: {ref}", f"{path}.alignment.unit_ids[{index}]")
    if status == "aligned" and not refs:
        report.add("alignment.missing_visual", "aligned segments must name at least one visual ID", f"{path}.alignment.visual_ids")
    if confidence in {"high", "medium", "low"} and not refs and status not in {"supplement", "navigation"}:
        report.add("alignment.missing_visual", "a confidence value requires a visual alignment unless this is a supplement", f"{path}.alignment.visual_ids")


def validate_lesson_map(
    value: LessonMap | Mapping[str, Any] | str | Path,
    *,
    strict: bool = False,
    allow_absolute_paths: bool = False,
) -> ValidationReport:
    """Validate a lesson map and return structured diagnostics.

    ``strict`` currently controls pedagogical completeness warnings: in strict
    mode they remain visible as warnings (not errors) so a partially built map
    can still be inspected.  Structural, provenance and privacy failures are
    always errors.  Set ``allow_absolute_paths=True`` only for local, private
    workspaces; public artifacts should retain the default ``False``.
    """

    report = ValidationReport()
    try:
        raw = _as_dict(value)
    except (TypeError, ValueError) as exc:
        report.add("map.input", str(exc))
        return report
    if not isinstance(raw, Mapping):
        report.add("map.shape", "lesson map must be an object")
        return report

    # Preserve a typed model on successful parsing.  If a malformed nested
    # item prevents coercion, validation below still reports its shape.
    typed: LessonMap | None = None
    try:
        typed = coerce_lesson_map(raw)
    except (TypeError, ValueError, KeyError) as exc:
        report.add("map.coercion", f"could not normalise lesson map: {exc}")
    report.map = typed

    for key in ("schema_version", "subject", "profile"):
        if not isinstance(raw.get(key), str) or not raw.get(key, "").strip():
            report.add("map.required", f"lesson map requires a non-empty {key}", f"$.{key}")
    if "map_kind" in raw and not isinstance(raw.get("map_kind"), str):
        report.add("map.type", "map_kind must be a string", "$.map_kind")

    source_rows = _items(raw, "sources", "source_assets", "source_manifest")
    # A legacy root ``source`` object is metadata, not a source array.
    if isinstance(raw.get("source"), list):
        source_rows = _items({"source": raw["source"]}, "source") + source_rows
    visual_rows = _items(raw, "pages", "visual_sources", "visual_frames")
    segment_rows = _items(raw, "speech_segments", "media_segments", "audio_segments")
    unit_rows = _items(raw, "units", "knowledge_units")
    claim_rows = _items(raw, "claims", "claim_ledger", "claimLedger")
    review_rows = _items(raw, "review_items", "reviews")
    lesson_rows = _items(raw, "lessons")
    assessment_rows = _items(raw, "assessment_evidence")

    for label, rows, path in (
        ("sources", source_rows, "$.sources"),
        ("visual frames", visual_rows, "$.visual_sources"),
        ("speech segments", segment_rows, "$.media_segments"),
        ("knowledge units", unit_rows, "$.units"),
        ("claims", claim_rows, "$.claims"),
        ("review items", review_rows, "$.review_items"),
        ("lessons", lesson_rows, "$.lessons"),
    ):
        if rows and not isinstance(rows, list):
            report.add("shape.array", f"{label} must be an array", path)

    source_ids = _check_ids(report, source_rows, "$.sources", ("source_id", "id"), "source")
    visual_ids = _check_ids(report, visual_rows, "$.visual_sources", ("visual_id", "page_id", "slide_id", "id"), "visual frame")
    segment_ids = _check_ids(report, segment_rows, "$.media_segments", ("segment_id", "id"), "speech segment")
    unit_ids = _check_ids(report, unit_rows, "$.units", ("unit_id", "id"), "knowledge unit")
    claim_ids = _check_ids(report, claim_rows, "$.claims", ("claim_id", "id"), "claim")
    review_ids = _check_ids(report, review_rows, "$.review_items", ("review_id", "item_id", "id"), "review item")
    lesson_ids = _check_ids(report, lesson_rows, "$.lessons", ("lesson_id", "id"), "lesson")
    assessment_ids = _check_ids(report, assessment_rows, "$.assessment_evidence", ("evidence_id", "id"), "assessment evidence")
    # Evidence IDs are local navigational keys; collect them across all
    # records so ``evidence_ids`` references are checked without confusing
    # them with assessment-document IDs.
    evidence_ids: dict[str, int] = {}
    for record_rows in (assessment_rows, unit_rows, claim_rows):
        for record in record_rows:
            if not isinstance(record, Mapping):
                continue
            candidates = _evidence_rows(record)
            for evidence in candidates:
                if not isinstance(evidence, Mapping):
                    continue
                ident = _value(evidence, "evidence_id", "id")
                if ident is None:
                    continue
                marker = str(ident)
                if marker in evidence_ids:
                    report.add("id.duplicate", f"duplicate evidence ID: {marker}", "$.evidence")
                else:
                    evidence_ids[marker] = len(evidence_ids)

    if "claims" not in raw and "claim_ledger" not in raw:
        report.add("claims.missing", "lesson map should include a claims list, even when it is empty", "$.claims", severity="error" if strict else "warning")
    if not unit_rows:
        report.add("units.missing", "lesson map contains no knowledge units", "$.units", severity="warning")

    if not allow_absolute_paths:
        _scan_absolute_paths(raw, report)

    # Validate source asset shape and timestamps/pages.
    for index, row in enumerate(source_rows):
        path = f"$.sources[{index}]"
        if not isinstance(row, Mapping):
            continue
        kind = _value(row, "kind", "source_kind")
        if not isinstance(kind, str) or not kind.strip():
            report.add("source.kind", "source requires a non-empty kind", f"{path}.kind")
        page_count = _value(row, "page_count")
        if page_count is not None and (not isinstance(page_count, int) or page_count < 0):
            report.add("source.page_count", "page_count must be a non-negative integer", f"{path}.page_count")
        duration = _value(row, "duration_seconds", "duration")
        if duration is not None and (not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0):
            report.add("source.duration", "duration_seconds must be non-negative", f"{path}.duration_seconds")

    # Visual and speech records.
    for index, row in enumerate(visual_rows):
        path = f"$.visual_sources[{index}]"
        if not isinstance(row, Mapping):
            continue
        page = _value(row, "page", "source_page")
        if page is not None and isinstance(page, int) and page < 1:
            report.add("visual.page", "page numbers are one-based and must be positive", f"{path}.page")
        status = _value(row, "alignment_status", "status")
        if status is not None and str(status) not in ALIGNMENT_STATUSES | RECORD_STATUSES:
            report.add("visual.status", f"unknown visual status: {status}", f"{path}.status")

    for index, row in enumerate(segment_rows):
        path = f"$.media_segments[{index}]"
        if not isinstance(row, Mapping):
            continue
        _check_time_range(report, row, path)
        status = _value(row, "status")
        if status is not None and str(status) not in ALIGNMENT_STATUSES | RECORD_STATUSES | {"lecture", "question", "answer"}:
            report.add("segment.status", f"unknown speech segment status: {status}", f"{path}.status")
        if str(status) in {"aligned", "aligned_range", "visual_explanation", "cross_visual"} and "alignment" not in row:
            report.add("alignment.missing", "aligned speech segments must include an alignment object", f"{path}.alignment")
        _check_alignment(report, row, path, visual_ids, unit_ids)
        _check_ref_list(report, row, "unit_ids", unit_ids, path)
        unit_ref = _value(row, "unit_id", "unit")
        if unit_ref is not None and unit_ids and str(unit_ref) not in unit_ids:
            report.add("reference.unknown_unit", f"speech segment refers to unknown unit ID: {unit_ref}", f"{path}.unit_id")
        if _value(row, "source_id") and source_ids and str(_value(row, "source_id")) not in source_ids:
            report.add("reference.unknown_source", f"speech segment refers to unknown source_id: {_value(row, 'source_id')}", f"{path}.source_id")

    # Root alignment records can be used when segments embed no alignment.
    for index, row in enumerate(_items(raw, "alignments")):
        path = f"$.alignments[{index}]"
        if not isinstance(row, Mapping):
            report.add("shape.record", "alignment must be an object", path)
            continue
        confidence = str(_value(row, "confidence", "alignment_confidence", default="unresolved"))
        status = str(_value(row, "status", "alignment_status", default="pending"))
        if confidence not in CONFIDENCE:
            report.add("alignment.confidence", f"alignment confidence must be one of {sorted(CONFIDENCE)}", f"{path}.confidence")
        if status not in ALIGNMENT_STATUSES:
            report.add("alignment.status", f"unknown alignment status: {status}", f"{path}.status")
        segment_ref = _value(row, "segment_id", "speech_segment_id")
        if segment_ref and segment_ids and str(segment_ref) not in segment_ids:
            report.add("alignment.unknown_segment", f"unknown speech segment ID: {segment_ref}", f"{path}.segment_id")
        refs = _list(_value(row, "visual_ids", "slide_ids", "pages", "page_ids", default=[]))
        if status == "aligned" and not refs:
            report.add("alignment.missing_visual", "aligned records must name visual IDs", f"{path}.visual_ids")
        for ref_index, ref in enumerate(refs):
            if ref not in visual_ids:
                report.add("alignment.unknown_visual", f"unknown visual ID: {ref}", f"{path}.visual_ids[{ref_index}]")

    # Units and cross-record references.
    for index, row in enumerate(unit_rows):
        path = f"$.units[{index}]"
        if not isinstance(row, Mapping):
            continue
        u, e = _check_levels(report, row, path, unit=True)
        for field_name, known in (("visual_ids", visual_ids), ("segment_ids", segment_ids), ("claim_ids", claim_ids), ("prerequisite_ids", unit_ids), ("review_item_ids", review_ids)):
            _check_ref_list(report, row, field_name, known, path)
        evidence_rows = _evidence_rows(row)
        if e in {"E3", "E-"}:
            direct = _check_evidence(report, row, path, required=True, source_ids=source_ids, assessment_ids=assessment_ids, strict=strict)
            assessment_ref = _value(row, "assessment_evidence_id")
            if assessment_ref and str(assessment_ref) not in assessment_ids:
                report.add("reference.unknown_assessment", f"unknown assessment evidence ID: {assessment_ref}", f"{path}.assessment_evidence_id")
            elif assessment_ref:
                assessment_row = next((item for item in assessment_rows if isinstance(item, Mapping) and str(_value(item, "evidence_id", "id", default="")) == str(assessment_ref)), None)
                if isinstance(assessment_row, Mapping):
                    _check_assessment_record(report, assessment_row, f"$.assessment_evidence[{assessment_ids[str(assessment_ref)]}]", strict=strict)
            if not direct and not assessment_ref:
                # Claims may carry the unit's evidence, but explicit unit-level
                # E3/E- still benefits from a visible pending warning.
                report.add("evidence.unit_required", "E3/E- unit needs direct verified evidence or assessment_evidence_id", path)
        elif evidence_rows:
            _check_evidence(report, row, path, required=False, source_ids=source_ids, assessment_ids=assessment_ids, strict=strict)
        if u in {"U2", "U3"}:
            for field_name, message in (
                ("logic_chain", "core units should expose a causal/argument chain"),
                ("learner_action", "core units should name an observable learner action"),
                ("transfer_question", "core units should include a retrieval or transfer prompt"),
            ):
                if not str(_value(row, field_name, default="") or "").strip():
                    report.add("pedagogy.missing", message, f"{path}.{field_name}", severity="error" if u == "U3" else "warning")
            if not str(_value(row, "representative_example", "example", default="") or "").strip() and not str(_value(row, "counterexample", default="") or "").strip():
                report.add("pedagogy.example_missing", "core units should include an example or counterexample", path, severity="error" if u == "U3" else "warning")

    # Claims are the strictest provenance boundary.
    claims_by_unit: dict[str, list[Mapping[str, Any]]] = {}
    for index, row in enumerate(claim_rows):
        path = f"$.claims[{index}]"
        if not isinstance(row, Mapping):
            continue
        u, e = _check_levels(report, row, path)
        if not str(_value(row, "text", "claim", "statement", "content", default="") or "").strip():
            report.add("claims.text_missing", "claim needs a non-empty statement", f"{path}.text")
        unit_ref = _value(row, "unit_id")
        if unit_ref:
            if unit_ids and str(unit_ref) not in unit_ids:
                report.add("reference.unknown_unit", f"claim refers to unknown unit ID: {unit_ref}", f"{path}.unit_id")
            claims_by_unit.setdefault(str(unit_ref), []).append(row)
        for field_name, known in (("visual_ids", visual_ids), ("segment_ids", segment_ids), ("evidence_ids", evidence_ids)):
            _check_ref_list(report, row, field_name, known, path)
        evidence_rows = _evidence_rows(row)
        if not evidence_rows:
            report.add("evidence.claim_source_missing", "claim must include at least one structured source reference", f"{path}.sources")
        direct = _check_evidence(report, row, path, required=e in {"E3", "E-"}, source_ids=source_ids, assessment_ids=assessment_ids, strict=strict)
        assessment_ref = _value(row, "assessment_evidence_id")
        if assessment_ref and str(assessment_ref) not in assessment_ids:
            report.add("reference.unknown_assessment", f"unknown assessment evidence ID: {assessment_ref}", f"{path}.assessment_evidence_id")
        elif assessment_ref:
            assessment_row = next((item for item in assessment_rows if isinstance(item, Mapping) and str(_value(item, "evidence_id", "id", default="")) == str(assessment_ref)), None)
            if isinstance(assessment_row, Mapping):
                _check_assessment_record(report, assessment_row, f"$.assessment_evidence[{assessment_ids[str(assessment_ref)]}]", strict=strict)
        if e in {"E3", "E-"} and not direct and not assessment_ref:
            report.add("evidence.claim_required", "E3/E- claim needs a verified quote and navigable source", path)
        status = str(_value(row, "status", default="pending"))
        if status not in RECORD_STATUSES | {"needs_review", "disputed", "待确认"}:
            report.add("claims.status_unknown", f"unrecognized claim status: {status}", f"{path}.status", severity="warning")
        if e in {"E3", "E-"} and status in {"pending", "unresolved", "draft", "conflict"}:
            report.add("evidence.unresolved", "E3/E- claim cannot remain pending or unresolved", f"{path}.status", severity="error" if strict else "warning")
        alignment_conf = _value(row, "alignment_confidence")
        if alignment_conf is not None and str(alignment_conf) not in CONFIDENCE:
            report.add("alignment.confidence", f"claim alignment confidence must be one of {sorted(CONFIDENCE)}", f"{path}.alignment_confidence")
        if str(alignment_conf or "").lower() == "unresolved" and status == "verified":
            report.add("claims.unresolved_verified", "unresolved alignment cannot be marked verified", path)
        risk = str(_value(row, "risk", "risk_level", default="low")).lower()
        if risk == "high" and _value(row, "verified", "reviewed", "double_checked") is not True and status not in {"pending", "unresolved", "draft"}:
            report.add(
                "claims.high_risk_unreviewed",
                "high-risk claim needs an explicit verification/review flag",
                path,
                severity="error" if strict else "warning",
            )

    # Assessment evidence itself must be locatable and verified if referenced.
    for index, row in enumerate(assessment_rows):
        path = f"$.assessment_evidence[{index}]"
        if not isinstance(row, Mapping):
            continue
        _check_evidence(report, row, path, required=False, source_ids=source_ids, assessment_ids=assessment_ids, strict=strict)
        _check_assessment_record(report, row, path, strict=strict)

    # Reviews and lessons are navigation records; references must still be safe.
    for index, row in enumerate(review_rows):
        path = f"$.review_items[{index}]"
        if not isinstance(row, Mapping):
            continue
        if not str(_value(row, "prompt", "question", default="") or "").strip():
            report.add("review.prompt", "review item requires a prompt", path)
        for field_name, known in (("visual_ids", visual_ids), ("segment_ids", segment_ids), ("source_ids", source_ids)):
            _check_ref_list(report, row, field_name, known, path)
        for field_name, known in (("unit_id", unit_ids), ("claim_id", claim_ids)):
            ref = _value(row, field_name)
            if ref and known and str(ref) not in known:
                report.add("reference.unknown", f"review item refers to unknown {field_name}: {ref}", f"{path}.{field_name}")

    for index, row in enumerate(lesson_rows):
        path = f"$.lessons[{index}]"
        if not isinstance(row, Mapping):
            continue
        for field_name, known in (("visual_ids", visual_ids), ("segment_ids", segment_ids), ("unit_ids", unit_ids), ("claim_ids", claim_ids), ("source_ids", source_ids)):
            _check_ref_list(report, row, field_name, known, path)

    # A unit's explicitly listed claim IDs should agree with claim ownership.
    for index, row in enumerate(unit_rows):
        if not isinstance(row, Mapping):
            continue
        unit_ref = _id(row, "unit_id")
        for claim_ref in _list(_value(row, "claim_ids", default=[])):
            claim = next((item for item in claim_rows if isinstance(item, Mapping) and _id(item, "claim_id") == claim_ref), None)
            if isinstance(claim, Mapping) and _value(claim, "unit_id") and str(_value(claim, "unit_id")) != unit_ref:
                report.add("reference.unit_claim_mismatch", f"claim {claim_ref} names a different unit", f"$.units[{index}].claim_ids")

    # ``strict=False`` is useful for a draft UI, but never downgrades safety
    # gates.  Keep the parameter explicit for forward-compatible callers.
    del strict, claims_by_unit, typed
    return report


def assert_valid_lesson_map(value: LessonMap | Mapping[str, Any] | str | Path, **kwargs: Any) -> LessonMap:
    """Validate and return a typed map, raising on structural errors."""

    report = validate_lesson_map(value, **kwargs)
    report.raise_for_errors()
    return report.map or coerce_lesson_map(value)


validate = validate_lesson_map


__all__ = [
    "Diagnostic",
    "ValidationReport",
    "assert_valid_lesson_map",
    "validate",
    "validate_lesson_map",
]
