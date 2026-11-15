"""Minimal fix lines and what-if comparison, both re-computed instead of guessed.

``suggest`` proposes one line to append to the ignore file, applies it to a copy
of the pattern list, runs the whole audit again and reports whether the problem
is gone and which other files came in or dropped out. ``compare`` does the same
kind of re-computation for a whole proposed ignore file. Nothing is written to disk.
"""
from __future__ import annotations

from _context import Walked
from _dockerfile import Parsed
from _matcher import Matcher
from _report import (
    FileResult,
    check_copies,
    classify,
    find_secrets,
    judge_source,
    normalize_source,
)


def _included(results: list[FileResult]) -> dict[str, int]:
    return {r.path: r.size for r in results if r.included}


def _side_effects(before: list[FileResult], after: list[FileResult]) -> dict:
    a, b = _included(before), _included(after)
    return {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b))}


def suggest(
    matcher: Matcher,
    results: list[FileResult],
    walked: Walked,
    copies: list[dict],
    secrets: list[dict],
    append_to: str,
) -> list[dict]:
    """One verified suggestion per COPY/ADD source that is excluded and per distinct secret fix line."""
    out: list[dict] = []
    cache: dict[str, tuple[Matcher, list[FileResult]]] = {}

    def apply(line: str) -> tuple[Matcher, list[FileResult]]:
        if line not in cache:
            m2 = matcher.with_line(line)
            cache[line] = (m2, classify(walked, m2))
        return cache[line]

    for check in copies:
        if check["status"] != "excluded":
            continue
        norm = normalize_source(check["source"])
        if norm is None:
            continue
        line = "!" + norm
        m2, r2 = apply(line)
        status, _rule, _note = judge_source(check["source"], r2, walked, m2)
        out.append(
            {
                "kind": "copy",
                "target": f"{check['instruction']} {check['source']}",
                "dockerfile_line": check["dockerfile_line"],
                "add_line": line,
                "append_to": append_to,
                "verified": status == "ok",
                "side_effects": _side_effects(results, r2),
            }
        )
    by_line: dict[str, list[str]] = {}
    for secret in secrets:
        by_line.setdefault(secret["rule_hint"], []).append(secret["path"])
    for line, paths in by_line.items():
        m2, r2 = apply(line)
        still = {r.path for r in r2 if r.included}
        gone = all(not any(p == s or (p.endswith("/") and s.startswith(p)) for s in still) for p in paths)
        out.append(
            {
                "kind": "secret",
                "target": "secret " + ", ".join(paths),
                "dockerfile_line": None,
                "add_line": line,
                "append_to": append_to,
                "verified": gone,
                "side_effects": _side_effects(results, r2),
            }
        )
    return out


def compare(
    base_results: list[FileResult],
    base_copies: list[dict],
    base_secrets: list[dict],
    other: Matcher,
    walked: Walked,
    parsed: Parsed,
) -> dict:
    """What changes if ``other`` replaced the ignore file: files, bytes, COPY status, secrets."""
    results = classify(walked, other)
    copies = check_copies(parsed, results, walked, other)
    secrets = find_secrets(results)
    effects = _side_effects(base_results, results)
    before, after = _included(base_results), _included(results)
    changes = [
        {
            "dockerfile_line": b["dockerfile_line"],
            "instruction": b["instruction"],
            "source": b["source"],
            "before": b["status"],
            "after": a["status"],
            "rule": a["rule"],
        }
        for b, a in zip(base_copies, copies)
        if b["status"] != a["status"]
    ]
    return {
        "file": other.source,
        "added": effects["added"],
        "removed": effects["removed"],
        "bytes_delta": sum(after.values()) - sum(before.values()),
        "copy_changes": changes,
        "secrets_before": len(base_secrets),
        "secrets_after": len(secrets),
    }
