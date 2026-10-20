"""Safe JSON and project-file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    """Read UTF-8 JSON and raise a useful error for a malformed artifact."""

    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"JSON input does not exist: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {source}: {exc}") from exc


def write_json(path: str | Path, value: Any) -> Path:
    """Write stable, human-readable UTF-8 JSON, creating only its parent."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return target


def project_paths(project_dir: str | Path) -> dict[str, Path]:
    """Return the conventional local project paths without touching the disk."""

    root = Path(project_dir)
    return {
        "root": root,
        "manifest": root / "project.json",
        "sources": root / "sources",
        "derived": root / "derived",
        "rendered": root / "derived" / "rendered",
        "lesson_map": root / "derived" / "lesson-map.json",
        "study_guide": root / "derived" / "study-guide.json",
        "generation_report": root / "derived" / "generation-report.json",
        "exports": root / "exports",
    }
