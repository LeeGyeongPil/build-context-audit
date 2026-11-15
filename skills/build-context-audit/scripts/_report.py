"""Judge every file, cross-check COPY/ADD sources, find secret-looking files and write hints.

All functions return plain dicts and lists so the same data feeds the text,
Markdown and JSON output. Status values and hint codes are language independent;
only hint messages are translated.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from _context import Walked
from _dockerfile import Instruction, Parsed, has_variable, is_remote
from _i18n import t
from _matcher import Evaluation, Matcher, Rule, clean_path, glob_regex

STATUSES = ("ok", "excluded", "missing", "skipped", "dynamic")

_DOT = "."  # names are assembled so this script holds no credential-looking literal
_ENV = _DOT + "env"
_ENV_SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")
_SSH_PREFIXES = ("id_" + "rsa", "id_" + "ed25519", "id_" + "ecdsa", "id_" + "dsa")
_EXACT_KINDS = {
    _DOT + "npmrc": "npmrc",
    _DOT + "pypirc": "pypirc",
    _DOT + "netrc": "netrc",
    "kubeconfig": "kubeconfig",
}
_AWS_CREDENTIALS = _DOT + "aws/credentials"

# Docker has no inline comments: "*.bak  # backups" is one pattern, spaces and '#' included.
_INLINE_COMMENT = re.compile(r"\s+#")
# Go character classes negate with '^'; "[!x]" is a set that holds '!' and 'x'.
_BANG_CLASS = re.compile(r"(?<!\\)\[!")


@dataclass
class FileResult:
    path: str
    size: int
    included: bool
    rule: Rule | None
    ev: Evaluation


def rule_dict(rule: Rule | None) -> dict | None:
    if rule is None:
        return None
    return {"file": rule.file, "line": rule.line, "pattern": rule.pattern}


def classify(walked: Walked, matcher: Matcher) -> list[FileResult]:
    """Evaluate every file of the context against the ordered patterns."""
    results: list[FileResult] = []
    for entry in walked.files:
        ev = matcher.evaluate(entry.path)
        results.append(FileResult(entry.path, entry.size, not ev.excluded, matcher.rule(ev.deciding), ev))
    return results


def totals(results: list[FileResult]) -> dict:
    inc = [r for r in results if r.included]
    exc = [r for r in results if not r.included]
    return {
        "included_files": len(inc),
        "included_bytes": sum(r.size for r in inc),
        "excluded_files": len(exc),
        "excluded_bytes": sum(r.size for r in exc),
    }


def top_dirs(results: list[FileResult], limit: int) -> list[dict]:
    """Largest first-level folders among the files that are sent (root files are grouped as ``.``)."""
    sizes: dict[str, list[int]] = {}
    for r in results:
        if not r.included:
            continue
        key = r.path.split("/", 1)[0] if "/" in r.path else "."
        bucket = sizes.setdefault(key, [0, 0])
        bucket[0] += r.size
        bucket[1] += 1
    rows = [{"path": k, "bytes": v[0], "files": v[1]} for k, v in sizes.items()]
    rows.sort(key=lambda row: (-row["bytes"], row["path"]))
    return rows[: max(limit, 0)]


# ---------------------------------------------------------------- COPY / ADD

def normalize_source(source: str) -> str | None:
    """Context-relative form of a COPY source, or None when it escapes the context."""
    s = source.strip().lstrip("/")
    s = posixpath.normpath(s) if s else "."
    if s == ".." or s.startswith("../"):
        return None
    return s


def _is_glob(s: str) -> bool:
    return any(ch in s for ch in "*?[")


def judge_source(source: str, results: list[FileResult], walked: Walked, matcher: Matcher) -> tuple[str, Rule | None, str | None]:
    """Status, deciding rule and note for one local COPY/ADD source."""
    norm = normalize_source(source)
    if norm is None:
        return "missing", None, "outside-context"
    by_path = {r.path: r for r in results}
    if _is_glob(norm):
        try:
            rx = re.compile(glob_regex(norm))
        except re.error:
            return "missing", None, "bad-glob"
        first_excluded: FileResult | None = None
        for r in results:
            pieces = r.path.split("/")
            candidates = ["/".join(pieces[: k + 1]) for k in range(len(pieces))]
            if any(rx.match(c) for c in candidates):
                if r.included:
                    return "ok", None, None
                first_excluded = first_excluded or r
        if first_excluded:
            return "excluded", first_excluded.rule, None
        return "missing", None, None
    if norm == ".":
        under = results
    elif norm in by_path:
        r = by_path[norm]
        return ("ok", None, None) if r.included else ("excluded", r.rule, None)
    else:
        under = [r for r in results if r.path.startswith(norm + "/")]
    if under:
        if any(r.included for r in under):
            return "ok", None, None
        first = under[0]
        if norm != ".":
            excluded, rule = matcher.decide(norm)
            if excluded:
                return "excluded", rule, None
        return "excluded", first.rule, None
    if norm in walked.dirs or norm == ".":
        excluded, rule = matcher.decide(norm)
        return ("excluded", rule, None) if excluded else ("ok", None, None)
    return "missing", None, None


def check_copies(parsed: Parsed, results: list[FileResult], walked: Walked, matcher: Matcher) -> list[dict]:
    """One entry per COPY/ADD source: ok | excluded | missing | skipped | dynamic."""
    checks: list[dict] = []

    def entry(ins: Instruction, source: str, status: str, rule: Rule | None, note: str | None) -> dict:
        return {
            "dockerfile_line": ins.line,
            "instruction": ins.keyword,
            "source": source,
            "status": status,
            "rule": rule_dict(rule),
            "note": note,
        }

    for ins in parsed.instructions:
        if ins.skip == "from":
            for src in ins.sources or [""]:
                checks.append(entry(ins, src, "skipped", None, "from"))
            continue
        if ins.skip == "heredoc":
            checks.append(entry(ins, "(heredoc)", "skipped", None, "heredoc"))
            continue
        if ins.skip == "unparsable":
            checks.append(entry(ins, "(unparsable)", "skipped", None, "unparsable"))
            continue
        for src in ins.sources:
            if ins.keyword == "ADD" and is_remote(src):
                checks.append(entry(ins, src, "skipped", None, "remote"))
            elif has_variable(src):
                checks.append(entry(ins, src, "dynamic", None, "variable"))
            else:
                status, rule, note = judge_source(src, results, walked, matcher)
                checks.append(entry(ins, src, status, rule, note))
    return checks


# ------------------------------------------------------------------- secrets

def secret_kind(path: str) -> tuple[str, str] | None:
    """(kind, ignore line that would remove it) for secret-looking names; file contents are never read."""
    base = path.rsplit("/", 1)[-1]
    low = base.lower()
    nested = "/" in path
    prefix = "**/" if nested else ""
    if low == _ENV or (low.startswith(_ENV + ".") and not low.endswith(_ENV_SAFE_SUFFIXES)):
        return "env", prefix + base
    if low.endswith((".pem", ".key")):
        return "private-key", prefix + "*" + low[low.rindex(".") :]
    if low.startswith(_SSH_PREFIXES) and not low.endswith(".pub"):
        return "ssh-key", prefix + base
    if low in _EXACT_KINDS:
        return _EXACT_KINDS[low], prefix + base
    if low.endswith(".tfstate"):
        return "terraform-state", prefix + "*.tfstate"
    if path == _AWS_CREDENTIALS or path.endswith("/" + _AWS_CREDENTIALS):
        return "aws-credentials", prefix + _DOT + "aws"
    return None


def find_secrets(results: list[FileResult]) -> list[dict]:
    """Secret-looking files that are sent to the builder, sorted by path (``.git/`` counted once per repo)."""
    found: list[dict] = []
    git_dirs: set[str] = set()
    for r in results:
        if not r.included:
            continue
        pieces = r.path.split("/")
        if ".git" in pieces[:-1]:
            k = pieces.index(".git")
            root = "/".join(pieces[: k + 1])
            if root not in git_dirs:
                git_dirs.add(root)
                found.append({"path": root + "/", "kind": "git-dir", "rule_hint": ("**/" if k else "") + ".git"})
            continue
        hit = secret_kind(r.path)
        if hit:
            found.append({"path": r.path, "kind": hit[0], "rule_hint": hit[1]})
    found.sort(key=lambda s: s["path"])
    return found


# --------------------------------------------------------------------- hints

def build_hints(matcher: Matcher, results: list[FileResult], parsed: Parsed | None, lang: str) -> list[dict]:
    """Diagnostics about the ignore file: anchoring, dead lines, shadowed exceptions, reference quirks."""
    hints: list[dict] = []
    pats = matcher.patterns
    matched_any = [False] * len(pats)
    flipped_any = [False] * len(pats)
    deciding_any = [False] * len(pats)
    for r in results:
        for idx in r.ev.matched:
            matched_any[idx] = True
        for idx in r.ev.flips:
            flipped_any[idx] = True
        if r.ev.deciding is not None:
            deciding_any[r.ev.deciding] = True
    for idx, pat in enumerate(pats):
        def add(code: str, key: str, **kw: object) -> None:
            hints.append({"code": code, "line": pat.line, "pattern": pat.display, "message": t(lang, key, **kw)})

        anchored_example = None
        if not pat.exclusion and not pat.text.startswith("**"):
            anchored_example = next(
                (p for r in results if r.included for p in [matcher.anchored_hint(idx, r.path)] if p), None
            )
        # a line that matches nothing only because it is root-anchored is explained by the anchoring hint alone
        # (an inline comment is explained by its own hint below)
        if not matched_any[idx]:
            if not anchored_example and not _INLINE_COMMENT.search(pat.text):
                add("unused-rule", "hint.unused.nomatch")
        elif not deciding_any[idx]:
            if pat.exclusion and flipped_any[idx]:
                add("shadowed-exception", "hint.shadowed")
            else:
                add("unused-rule", "hint.unused.covered")
        if anchored_example:
            add("root-anchored", "hint.root", pattern=pat.text, example=anchored_example, wide="**/" + pat.text)
        if pat.text.startswith("**") and len(pat.text) > 2 and pat.text[2] != "/" and pat.kind == "suffix":
            suffix = pat.text[2:]
            example = next(
                (r.path for r in results if r.path.endswith(suffix) and r.path.rsplit("/", 1)[-1] != suffix), None
            )
            if example:
                add("suffix-match", "hint.suffix.example", pattern=pat.display, suffix=suffix, example=example)
            else:
                add("suffix-match", "hint.suffix", pattern=pat.display, suffix=suffix)
        # "*.bak  # editor backups": the whole line is the pattern, so '*.bak' never applies
        comment = _INLINE_COMMENT.search(pat.text)
        if comment:
            add("inline-comment", "hint.inline_comment", pattern=pat.display, meant=pat.text[: comment.start()])
        # "[!R]*.md" excludes README.md (names starting with '!' or 'R'), the opposite of the shell meaning
        if _BANG_CLASS.search(pat.text):
            fixed = _BANG_CLASS.sub("[^", pat.text)
            add("bang-class", "hint.bang_class", fixed=fixed)
    if parsed is not None and parsed.escape_directive_line:
        hints.append(
            {
                "code": "escape-directive",
                "line": parsed.escape_directive_line,
                "pattern": "",
                "message": t(lang, "hint.escape"),
            }
        )
    hints.sort(key=lambda h: (h["code"] == "escape-directive", h["line"], h["code"]))
    return hints


# ------------------------------------------------------------------- explain

def explain(path: str, matcher: Matcher, results: list[FileResult], walked: Walked, lang: str) -> dict:
    """Why one path is sent or not: every matching line in order and the line that decided."""
    norm = clean_path(path.strip().lstrip("/") or ".")
    known = {r.path: r for r in results}
    ev = matcher.evaluate(norm)
    kind = "file" if norm in known else ("dir" if norm in walked.dirs else "unknown")
    history = []
    for idx in ev.matched:
        pat = matcher.patterns[idx]
        if idx in ev.flips:
            effect = "include" if pat.exclusion else "exclude"
        else:
            effect = "no-effect"
        history.append(
            {
                "file": matcher.source,
                "line": pat.line,
                "pattern": pat.display,
                "effect": effect,
                "deciding": idx == ev.deciding,
            }
        )
    notes: list[str] = []
    for idx, pat in enumerate(matcher.patterns):
        if idx in ev.matched or pat.exclusion or pat.text.startswith("**"):
            continue
        prefix = matcher.anchored_hint(idx, norm)
        if prefix:
            notes.append(t(lang, "explain.anchored", line=pat.line, pattern=pat.text, prefix=prefix, wide="**/" + pat.text))
    return {
        "path": norm,
        "kind": kind,
        "size": known[norm].size if norm in known else None,
        "included": not ev.excluded,
        "rule": rule_dict(matcher.rule(ev.deciding)),
        "history": history,
        "notes": notes,
    }
