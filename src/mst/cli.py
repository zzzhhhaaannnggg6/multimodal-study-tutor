"""Command-line interface for local-first study projects."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import StudyAgent
from .export import export_markdown, export_study_guide
from .guide import generate_project_guide, validate_study_guide
from .ingest import ingest_project, init_project, transcribe_project_audio
from .io import active_project_dir, project_paths, read_json
from .models import LessonMap
from .profiles import list_profiles
from .reconstruct import build_scaffold, inspect_project_visuals
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

    quickstart = sub.add_parser("quickstart", help="create a project and generate a guide from course files")
    quickstart.add_argument("project", type=Path)
    quickstart.add_argument("inputs", nargs="+", type=Path)
    quickstart.add_argument("--subject", default="generic")
    quickstart.add_argument("--provider", choices=("none", "mock", "openai"), default="none")
    quickstart.add_argument("--model", default="gpt-5-mini")
    quickstart.add_argument("--render", action=argparse.BooleanOptionalAction, default=True, help="render PPT/PDF pages for visual review")
    quickstart.add_argument("--vision-provider", choices=("none", "openai"), default="none")
    quickstart.add_argument("--vision-model", default="gpt-5-mini")
    quickstart.add_argument("--strict", action="store_true")

    ingest = sub.add_parser("ingest", help="record input files without modifying them")
    ingest.add_argument("project", type=Path)
    ingest.add_argument("inputs", nargs="+", type=Path)

    build = sub.add_parser("build", help="create a provenance scaffold")
    build.add_argument("project", type=Path)
    build.add_argument("--render", action=argparse.BooleanOptionalAction, default=True, help="render PPT/PDF pages for visual review")

    generate = sub.add_parser("generate", help="generate a student-facing self-study guide")
    generate.add_argument("project", type=Path)
    generate.add_argument("--provider", choices=("none", "mock", "openai"), default="none")
    generate.add_argument("--model", default="gpt-5-mini")
    generate.add_argument("--speech-provider", choices=("none", "openai"), default="none")
    generate.add_argument("--speech-model", default="gpt-4o-transcribe")
    generate.add_argument("--strict", action="store_true", help="fail if the guide is incomplete")
    generate.add_argument("--vision-provider", choices=("none", "openai"), default="none")
    generate.add_argument("--vision-model", default="gpt-5-mini")

    validate = sub.add_parser("validate", help="validate a lesson-map JSON")
    validate.add_argument("map", type=Path, nargs="?", default=None)
    validate.add_argument("--project", type=Path, default=None)
    validate.add_argument("--strict", action="store_true")

    validate_guide = sub.add_parser("validate-guide", help="validate a student study-guide JSON")
    validate_guide.add_argument("map", type=Path)
    validate_guide.add_argument("--strict", action="store_true")

    evaluate = sub.add_parser("evaluate", help="run a local synthetic numerical teaching benchmark")
    evaluate.add_argument("suite", type=Path)
    evaluate.add_argument("--guides-dir", type=Path, help="check precomputed case-ID JSON guides instead of generating offline")
    evaluate.add_argument("--save-guides", type=Path, help="save synthetic candidate guides for inspection")
    evaluate.add_argument("--output", type=Path, help="save a machine-readable evaluation report")

    export = sub.add_parser("export", help="export a Markdown study note")
    export.add_argument("project", type=Path)
    export.add_argument("--output", type=Path)
    export.add_argument("--format", choices=("md", "html", "json"), default="md")

    serve = sub.add_parser("serve", help="serve the local student study route")
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
    if args.command == "evaluate":
        from .evaluation import evaluate_suite
        from .io import write_json

        try:
            report = evaluate_suite(args.suite, guides_dir=args.guides_dir, save_guides=args.save_guides)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            print(f"Evaluation suite is invalid: {exc}", file=sys.stderr)
            return 2
        if args.output:
            write_json(args.output, report)
        print(f"{report['suite_id']}: {report['passed']}/{report['total']} synthetic cases passed; {report['failed']} failed")
        for result in report["results"]:
            if not result["passed"]:
                print(f"FAIL {result['case_id']}: {', '.join(result['failures'])}")
        print(report["scope"])
        return 1 if report["failed"] else 0
    if args.command in {"ingest", "build", "generate", "export", "validate"} and getattr(args, "project", None):
        args.project = active_project_dir(args.project)
    if args.command == "init":
        manifest = init_project(args.project, args.subject)
        print(f"Initialized {args.project} ({manifest['profile']})")
        return 0
    if args.command == "quickstart":
        if not project_paths(args.project)["manifest"].exists():
            manifest = init_project(args.project, args.subject)
            print(f"Initialized {args.project} ({manifest['profile']})")
        manifest = ingest_project(args.project, args.inputs)
        print(f"Recorded {len(manifest['source_manifest'])} source(s)")
        data = build_scaffold(args.project, render=args.render)
        print(f"Built scaffold with {len(data['pages'])} visual source(s)")
        if args.vision_provider == "openai":
            from .providers import OpenAIVisionProvider

            inspected = inspect_project_visuals(args.project, OpenAIVisionProvider(args.vision_model))
            print(f"Inspected {inspected} rendered page image(s) with vision provider")
        provider = None
        if args.provider == "mock":
            from .providers import MockProvider

            provider = MockProvider()
        elif args.provider == "openai":
            from .providers import OpenAIProvider

            provider = OpenAIProvider(args.model)
        guide = generate_project_guide(args.project, provider)
        report = validate_study_guide(guide, strict=args.strict)
        print(f"Generated {guide.report.status} study guide: {len(guide.units)} unit(s)")
        print(
            f"Pages {guide.report.covered_pages}/{guide.report.total_pages} text-covered; "
            f"{guide.report.visual_review_pages} visual review pending; "
            f"speech alignment {guide.report.aligned_segments}/{guide.report.total_segments}"
        )
        print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        if args.strict and (report.errors or guide.report.status != "complete"):
            return 1
        return 0
    if args.command == "ingest":
        manifest = ingest_project(args.project, args.inputs)
        print(f"Recorded {len(manifest['source_manifest'])} source(s)")
        return 0
    if args.command == "build":
        data = build_scaffold(args.project, render=args.render)
        print(f"Built scaffold with {len(data['pages'])} visual source(s)")
        return 0
    if args.command == "generate":
        provider = None
        if args.speech_provider == "openai":
            from .providers import OpenAISpeechProvider

            added = transcribe_project_audio(args.project, OpenAISpeechProvider(args.speech_model))
            print(f"Transcribed {added} audio segment(s)")
        if args.vision_provider == "openai":
            from .providers import OpenAIVisionProvider

            inspected = inspect_project_visuals(args.project, OpenAIVisionProvider(args.vision_model))
            print(f"Inspected {inspected} rendered page image(s) with vision provider")
        if args.provider == "mock":
            from .providers import MockProvider

            provider = MockProvider()
        elif args.provider == "openai":
            from .providers import OpenAIProvider

            provider = OpenAIProvider(args.model)
        guide = generate_project_guide(args.project, provider)
        report = validate_study_guide(guide, strict=args.strict)
        print(f"Generated {guide.report.status} study guide: {len(guide.units)} unit(s)")
        print(
            f"Pages {guide.report.covered_pages}/{guide.report.total_pages} text-covered; "
            f"{guide.report.visual_review_pages} visual review pending; "
            f"speech alignment {guide.report.aligned_segments}/{guide.report.total_segments}"
        )
        for item in report.diagnostics:
            print(f"{item.severity.upper()} {item.path}: {item.message} [{item.code}]")
        print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        if args.strict and (report.errors or guide.report.status != "complete"):
            return 1
        return 0
    if args.command == "validate":
        map_path = args.map or (project_paths(args.project)["lesson_map"] if args.project else None)
        if map_path is None:
            raise SystemExit("provide a map path or --project")
        raw = read_json(map_path)
        if isinstance(raw, dict) and raw.get("guide_kind") == "student-study-guide":
            report = validate_study_guide(raw, strict=args.strict)
        else:
            report = validate_lesson_map(raw, strict=args.strict)
        for item in report.diagnostics:
            print(f"{item.severity.upper()} {item.path}: {item.message} [{item.code}]")
        print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        if args.strict and isinstance(raw, dict) and raw.get("guide_kind") == "student-study-guide" and (
            report.errors or raw.get("generation_report", {}).get("status") != "complete"
        ):
            return 1
        return 1 if report.errors else 0
    if args.command == "validate-guide":
        raw = read_json(args.map)
        report = validate_study_guide(raw, strict=args.strict)
        for item in report.diagnostics:
            print(f"{item.severity.upper()} {item.path}: {item.message} [{item.code}]")
        print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        if args.strict and (report.errors or raw.get("generation_report", {}).get("status") != "complete"):
            return 1
        return 1 if report.errors else 0
    if args.command == "export":
        if args.format == "md" and not project_paths(args.project)["study_guide"].exists():
            target = export_markdown(args.project, args.output)
        else:
            target = export_study_guide(args.project, args.output, format=args.format)
        print(f"Wrote {target}")
        return 0
    if args.command == "serve":
        from .server import serve

        try:
            serve(args.project, args.host, args.port, args.open_browser)
            return 0
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
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
