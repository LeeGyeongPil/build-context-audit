#!/usr/bin/env python3
"""Audit a docker build context before building.

Computes, with the Docker CLI's .dockerignore semantics and without a Docker daemon,
which files the builder receives, which ignore-file line decided each one, which
COPY/ADD sources will fail, and which secret-looking files slip in. Optionally
explains single paths, proposes verified fix lines and compares a proposed ignore file.

Exit codes: 0 nothing found, 1 findings at the --fail-on level, 2 usage or file error,
3 ignore-file syntax error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from _context import walk
from _dockerfile import Parsed, parse
from _i18n import LANGS, resolve_lang, t
from _ignorefile import choose, display_path, read_lines
from _matcher import IgnoreSyntaxError, Matcher
from _render import render_md, render_text
from _report import build_hints, check_copies, classify, explain, find_secrets, top_dirs, totals
from _suggest import compare, suggest

VERSION = "0.1.0"
EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_SYNTAX = 0, 1, 2, 3


class Fail(Exception):
    """A user-facing failure: the message lines go to stderr and ``code`` is the exit code."""

    def __init__(self, code: int, lines: list[str]) -> None:
        super().__init__(lines[0])
        self.code = code
        self.lines = lines


def _scan_lang(argv: Sequence[str]) -> str | None:
    """Find --lang before argparse runs, so the help text itself can be translated."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_parser(lang: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audit.py",
        description=t(lang, "help.description"),
        epilog=t(lang, "help.epilog"),
        allow_abbrev=False,
        add_help=False,
    )
    p.add_argument("-h", "--help", action="help", help=t(lang, "help.help"))
    p.add_argument("context", metavar="CONTEXT", help=t(lang, "help.context"))
    p.add_argument("-f", "--file", metavar="DOCKERFILE", help=t(lang, "help.file"))
    p.add_argument("--ignore-file", metavar="FILE", help=t(lang, "help.ignore_file"))
    p.add_argument("--explain", metavar="PATH", action="append", default=[], help=t(lang, "help.explain"))
    p.add_argument("--suggest", action="store_true", help=t(lang, "help.suggest"))
    p.add_argument("--compare-ignore", metavar="FILE", help=t(lang, "help.compare"))
    p.add_argument("--list", choices=["included", "excluded", "all"], dest="list_mode", help=t(lang, "help.list"))
    p.add_argument("--max-list", type=int, default=50, metavar="N", help=t(lang, "help.max_list"))
    p.add_argument("--top", type=int, default=5, metavar="N", help=t(lang, "help.top"))
    p.add_argument("--format", choices=["text", "md", "json"], default="text", help=t(lang, "help.format"))
    p.add_argument("--out", metavar="FILE", help=t(lang, "help.out"))
    p.add_argument("--fail-on", choices=["error", "warning", "never"], default="error", help=t(lang, "help.fail_on"))
    p.add_argument("--lang", choices=list(LANGS), help=t(lang, "help.lang"))
    p.add_argument("--version", action="version", version=f"build-context-audit {VERSION}", help=t(lang, "help.version"))
    return p


def _load_matcher(path: Path, context: Path, lang: str) -> Matcher:
    """Read an ignore file and compile it; unreadable is exit 2, bad syntax is exit 3."""
    name = display_path(path, context)
    try:
        lines = read_lines(path)
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        raise Fail(EXIT_USAGE, [t(lang, "error.read", path=path, reason=reason), t(lang, "error.read.fix")]) from exc
    try:
        return Matcher(lines, source=name)
    except IgnoreSyntaxError as exc:
        if exc.kind == "illegal-exclusion":
            raise Fail(EXIT_SYNTAX, [t(lang, "error.illegal", file=name, line=exc.line), t(lang, "error.illegal.fix")]) from exc
        raise Fail(
            EXIT_SYNTAX,
            [t(lang, "error.pattern", file=name, line=exc.line, pattern=exc.pattern), t(lang, "error.pattern.fix")],
        ) from exc


def _find_dockerfile(context: Path, given: str | None, lang: str) -> tuple[Path, bool]:
    """(path, exists). An explicit -f must exist; it is tried relative to the working folder, then the context."""
    if given:
        path = Path(given)
        if path.is_file():
            return path, True
        alt = context / given
        if alt.is_file():
            return alt, True
        raise Fail(EXIT_USAGE, [t(lang, "error.dockerfile", path=given), t(lang, "error.dockerfile.fix")])
    default = context / "Dockerfile"
    return default, default.is_file()


def _relative_explain_path(raw: str, context: Path) -> str:
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(context.resolve()).as_posix()
        except ValueError:
            return raw
    return raw[2:] if raw.startswith("./") else raw


def analyze(args: argparse.Namespace, lang: str) -> dict:
    """Run the whole audit and return the report dict."""
    context = Path(args.context)
    if not context.is_dir():
        raise Fail(EXIT_USAGE, [t(lang, "error.context", path=args.context), t(lang, "error.context.fix")])
    dockerfile, has_dockerfile = _find_dockerfile(context, args.file, lang)
    choice = choose(context, dockerfile, args.ignore_file)
    if choice.path is not None:
        matcher = _load_matcher(choice.path, context, lang)
    else:
        matcher = Matcher([], source=".dockerignore")
    other = _load_matcher(Path(args.compare_ignore), context, lang) if args.compare_ignore else None

    notes: list[dict] = []
    parsed = Parsed()
    if has_dockerfile:
        try:
            parsed = parse(dockerfile.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
            raise Fail(EXIT_USAGE, [t(lang, "error.read", path=dockerfile, reason=reason), t(lang, "error.read.fix")]) from exc
    else:
        notes.append({"code": "no-dockerfile", "message": t(lang, "note.no_dockerfile", path=dockerfile)})

    walked = walk(context)
    if walked.unreadable:
        notes.append({"code": "unreadable", "message": t(lang, "note.unreadable", paths=", ".join(walked.unreadable[:5]))})
    results = classify(walked, matcher)
    copies = check_copies(parsed, results, walked, matcher) if has_dockerfile else []
    secrets = find_secrets(results)
    hints = build_hints(matcher, results, parsed if has_dockerfile else None, lang)

    append_to = choice.display or ".dockerignore"
    suggestions = suggest(matcher, results, walked, copies, secrets, append_to) if args.suggest else []
    comparison = compare(results, copies, secrets, other, walked, parsed) if other else None

    rep: dict = {
        "context": args.context,
        "dockerfile": display_path(dockerfile, context) if has_dockerfile else None,
        "ignore_file": choice.display,
        "ignore_file_reason": choice.reason,
        "root_ignore_unused": choice.reason == "dockerfile-specific" and choice.root_exists,
        "totals": totals(results),
        "top_dirs": top_dirs(results, args.top),
        "copy_checks": copies,
        "secrets": secrets,
        "hints": hints,
        "explain": [
            explain(_relative_explain_path(p, context), matcher, results, walked, lang) for p in args.explain
        ],
        "suggest_requested": bool(args.suggest),
        "suggestions": suggestions,
        "compare": comparison,
        "notes": notes,
        "list_mode": args.list_mode,
    }
    if args.list_mode:
        want = {"included": (True,), "excluded": (False,), "all": (True, False)}[args.list_mode]
        rep["files"] = [
            {
                "path": r.path,
                "size": r.size,
                "included": r.included,
                "rule": None if r.rule is None else {"file": r.rule.file, "line": r.rule.line, "pattern": r.rule.pattern},
            }
            for r in results
            if r.included in want
        ]
    problems = sum(1 for c in copies if c["status"] in ("excluded", "missing"))
    warnings = len(hints) + sum(1 for c in copies if c["status"] == "dynamic")
    rep["summary"] = {"copy_problems": problems, "secrets": len(secrets), "warnings": warnings}
    return rep


def exit_code(rep: dict, fail_on: str) -> int:
    """1 when a finding reaches the --fail-on level, else 0."""
    s = rep["summary"]
    if fail_on == "never":
        return EXIT_OK
    errors = s["copy_problems"] > 0 or s["secrets"] > 0
    if errors or (fail_on == "warning" and s["warnings"] > 0):
        return EXIT_FINDINGS
    return EXIT_OK


def render(rep: dict, fmt: str, lang: str, max_list: int) -> str:
    if fmt == "json":
        data = {k: v for k, v in rep.items() if k not in ("suggest_requested", "list_mode", "root_ignore_unused")}
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if fmt == "md":
        return render_md(rep, lang, max_list)
    return render_text(rep, lang, max_list)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    args_list = list(sys.argv[1:] if argv is None else argv)
    lang = resolve_lang(_scan_lang(args_list), env)
    args = build_parser(lang).parse_args(args_list)
    lang = resolve_lang(args.lang, env)
    if args.max_list < 0 or args.top < 0:
        print("error: --max-list and --top must be 0 or more", file=sys.stderr)
        return EXIT_USAGE
    try:
        rep = analyze(args, lang)
    except Fail as fail:
        print("\n".join(fail.lines), file=sys.stderr)
        return fail.code
    text = render(rep, args.format, lang, args.max_list)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as exc:
            print(t(lang, "error.out", path=args.out, reason=exc.strerror or exc), file=sys.stderr)
            return EXIT_USAGE
    else:
        sys.stdout.write(text)
    return exit_code(rep, args.fail_on)


if __name__ == "__main__":
    sys.exit(main())
