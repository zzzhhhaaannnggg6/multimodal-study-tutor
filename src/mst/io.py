"""Safe JSON and project-file helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
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
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def active_project_dir(project_dir: str | Path) -> Path:
    """Resolve the last fully published web run, or retain a legacy project."""
    root = Path(project_dir).resolve()
    pointer = root / ".study-state.json"
    if not pointer.is_file():
        return root
    state = read_json(pointer)
    run_id = state.get("active_run", "") if isinstance(state, dict) else ""
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("当前课程记录无效；已有课程文件仍保留在本地。")
    target = root / ".study-jobs" / run_id / "workspace"
    if not target.is_dir() or not target.resolve().is_relative_to(root / ".study-jobs"):
        raise ValueError("当前课程文件不可用；请在任务记录中重新生成。")
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
