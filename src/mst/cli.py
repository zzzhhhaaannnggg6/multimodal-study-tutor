"""Command-line interface for local-first study projects."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import StudyAgent
from .export import export_markdown
from .ingest import ingest_project, init_project
from .io import project_paths, read_json
from .models import LessonMap
from .profiles import list_profiles
from .reconstruct import build_scaffold
from .validation import validate_lesson_map


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="study",
        description="Build traceable lessons from visual materials and teacher speech.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a local study project")
    init.add_argument("project", type=Path)
    init.add_argument("--subject", default="generic")

    ingest = sub.add_parser("ingest", help="record input files without modifying them")
    ingest.add_argument("project", type=Path)
    ingest.add_argument("inputs", nargs="+", type=Path)

    build = sub.add_parser("build", help="create a provenance scaffold")
    build.add_argument("project", type=Path)

    validate = sub.add_parser("validate", help="validate a lesson-map JSON")
    validate.add_argument("map", type=Path, nargs="?", default=None)
    validate.add_argument("--project", type=Path, default=None)
    validate.add_argument("--strict", action="store_true")

    export = sub.add_parser("export", help="export a Markdown study note")
    export.add_argument("project", type=Path)
    export.add_argument("--output", type=Path)

    serve = sub.add_parser("serve", help="serve the local timeline demo")
    serve.add_argument("project", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", dest="open_browser")

    ask = sub.add_parser("ask", help="query a lesson map with a local or model provider")
    ask.add_argument("map", type=Path)
    ask.add_argument("question")
    ask.add_argument("--provider", choices=("mock", "openai"), default="mock")
    ask.add_argument("--model", default="gpt-5-mini")

    sub.add_parser("profiles", help="list bundled subject profiles")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        manifest = init_project(args.project, args.subject)
        print(f"Initialized {args.project} ({manifest['profile']})")
        return 0
    if args.command == "ingest":
        manifest = ingest_project(args.project, args.inputs)
        print(f"Recorded {len(manifest['source_manifest'])} source(s)")
        return 0
    if args.command == "build":
        data = build_scaffold(args.project)
        print(f"Built scaffold with {len(data['pages'])} visual source(s)")
        return 0
    if args.command == "validate":
        map_path = args.map or (project_paths(args.project)["lesson_map"] if args.project else None)
        if map_path is None:
            raise SystemExit("provide a map path or --project")
        report = validate_lesson_map(read_json(map_path), strict=args.strict)
        for item in report.diagnostics:
            print(f"{item.severity.upper()} {item.path}: {item.message} [{item.code}]")
        print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        return 1 if report.errors else 0
    if args.command == "export":
        target = export_markdown(args.project, args.output)
        print(f"Wrote {target}")
        return 0
    if args.command == "serve":
        from .server import serve

        serve(args.project, args.host, args.port, args.open_browser)
        return 0
    if args.command == "ask":
        data = read_json(args.map)
        lesson_map = LessonMap.from_dict(data)
        provider = None
        if args.provider == "openai":
            from .providers import OpenAIProvider

            provider = OpenAIProvider(args.model)
        agent = StudyAgent(lesson_map, provider)
        print(agent.explain(args.question))
        return 0
    if args.command == "profiles":
        for profile in list_profiles():
            print(f"{profile.profile_id}\t{profile.label}\t{profile.trace_template}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
