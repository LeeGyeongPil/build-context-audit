"""Ignore-file reading and pattern matching with the same meaning as the Docker CLI.

Clean-room implementation of the observable behaviour of the reference matcher
(moby/patternmatcher): patterns are anchored at the context root, ``*`` and ``?``
never cross ``/``, ``**`` spans directories, a match on any parent directory
counts, the last line that changes the verdict decides. The verdict is built
folder by folder the way the builder walks the context (a line skipped for a
folder because it could not change that folder's verdict does not reach the
files below it). Every decision also reports which line decided it.

Matching is plain string work on slash-separated paths, never ``fnmatch``,
so the answer does not depend on the platform's case rules: ``secret.txt``
does not match ``Secret.txt``.
"""
from __future__ import annotations

import posixpath
import re
import warnings
from dataclasses import dataclass, field

_REGEX_ESCAPED = set(".+()|{}$")


class IgnoreSyntaxError(ValueError):
    """An ignore-file line that Docker would reject."""

    def __init__(self, line: int, pattern: str, kind: str) -> None:
        super().__init__(f"line {line}: {kind}: {pattern!r}")
        self.line = line
        self.pattern = pattern
        self.kind = kind  # "invalid-pattern" | "illegal-exclusion"


@dataclass(frozen=True)
class IgnoreLine:
    """One effective ignore-file line: its 1-based line number and cleaned text."""

    number: int
    text: str  # includes a leading "!" for exceptions


@dataclass(frozen=True)
class Rule:
    """The line that decided a verdict."""

    file: str
    line: int
    pattern: str


@dataclass
class Evaluation:
    """Everything one path learned from the ordered pattern list."""

    excluded: bool = False
    deciding: int | None = None  # index into Matcher.patterns of the last line that changed the verdict
    flips: list[int] = field(default_factory=list)
    matched: list[int] = field(default_factory=list)  # every line that matches, even when skipped
    # line index -> parent folder: lines that match only through that folder, were skipped there because they could
    # not change the folder's verdict at that point, and so never reach this path although they would change its
    # verdict at that point if they did (used to explain, not to decide)
    folder_skipped: dict[int, str] = field(default_factory=dict)


def clean_path(p: str) -> str:
    """Lexical path clean (no filesystem access): ``./a//b/`` -> ``a/b``."""
    if p == "":
        return "."
    rooted = p.startswith("/")
    out: list[str] = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out and out[-1] != "..":
                out.pop()
            elif not rooted:
                out.append("..")
            continue
        out.append(part)
    joined = "/".join(out)
    if rooted:
        return "/" + joined
    return joined or "."


def read_ignore_lines(text: str) -> list[IgnoreLine]:
    """Apply the reading rules and keep original line numbers.

    Only a ``#`` in column 1 starts a comment, surrounding spaces are trimmed,
    blank lines are dropped, a UTF-8 BOM on the first line is removed, a ``!``
    prefix marks an exception, paths are cleaned and a leading ``/`` is removed.
    """
    result: list[IgnoreLine] = []
    for index, raw in enumerate(text.splitlines()):
        line = raw
        if index == 0 and line.startswith("﻿"):
            line = line[1:]
        if line.startswith("#"):
            continue
        line = line.strip()
        if not line:
            continue
        negated = line[0] == "!"
        if negated:
            line = line[1:].strip()
        if line:
            line = clean_path(line)
            if len(line) > 1 and line[0] == "/":
                line = line[1:]
        result.append(IgnoreLine(index + 1, ("!" if negated else "") + line))
    return result


def _check_syntax(p: str) -> bool:
    """True when the glob syntax is valid (character classes, escapes)."""
    i, n = 0, len(p)

    def class_char(j: int) -> int:
        if j >= n or p[j] in "-]":
            return -1
        if p[j] == "\\":
            j += 1
            if j >= n:
                return -1
        return j + 1

    while i < n:
        c = p[i]
        if c == "\\":
            if i + 1 >= n:
                return False
            i += 2
        elif c == "[":
            i += 1
            if i < n and p[i] == "^":
                i += 1
            ranges = 0
            while True:
                if i < n and p[i] == "]" and ranges > 0:
                    i += 1
                    break
                i = class_char(i)
                if i < 0:
                    return False
                if i < n and p[i] == "-":
                    i = class_char(i + 1)
                    if i < 0:
                        return False
                ranges += 1
        else:
            i += 1
    return True


def glob_regex(p: str) -> str:
    """Regex source for one glob (``*``/``?`` stay inside a path segment)."""
    return _compile(p)[1]


def _compile(p: str) -> tuple[str, str]:
    """Return (kind, regex source) with kind in exact | prefix | suffix | regexp."""
    rs = "^"
    kind = "exact"
    i, n = 0, len(p)
    first = True
    while i < n:
        c = p[i]
        if c == "*":
            if i + 1 < n and p[i + 1] == "*":
                i += 2
                if i < n and p[i] == "/":
                    i += 1
                if i >= n:
                    if kind == "exact":
                        kind = "prefix"
                    else:
                        rs += ".*"
                        kind = "regexp"
                else:
                    rs += "(.*/)?"
                    kind = "regexp"
                if first:
                    kind = "suffix"
                first = False
                continue
            rs += "[^/]*"
            kind = "regexp"
        elif c == "?":
            rs += "[^/]"
            kind = "regexp"
        elif c in _REGEX_ESCAPED:
            rs += "\\" + c
        elif c == "\\":
            if i + 1 < n:
                i += 1
                rs += "\\" + p[i]
                kind = "regexp"
            else:
                rs += "\\\\"
        elif c in "[]":
            rs += c
            kind = "regexp"
        else:
            rs += c
        i += 1
        first = False
    return kind, rs + "$"


class Pattern:
    """One compiled ignore pattern."""

    def __init__(self, text: str, line: int, exclusion: bool) -> None:
        self.text = text
        self.line = line
        self.exclusion = exclusion  # True for a "!" exception
        self.kind, source = _compile(text)
        self.regex: re.Pattern[str] | None = None
        if self.kind == "regexp":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    self.regex = re.compile(source)
                except re.error as exc:
                    raise IgnoreSyntaxError(line, text, "invalid-pattern") from exc

    @property
    def display(self) -> str:
        return ("!" if self.exclusion else "") + self.text

    def matches(self, path: str) -> bool:
        if self.kind == "exact":
            return path == self.text
        if self.kind == "prefix":
            return path.startswith(self.text[:-2])
        if self.kind == "suffix":
            suffix = self.text[2:]
            if path.endswith(suffix):
                return True
            return bool(suffix) and suffix[0] == "/" and path == suffix[1:]
        assert self.regex is not None
        return bool(self.regex.match(path))


class Matcher:
    """An ordered list of patterns from one ignore file."""

    def __init__(self, lines: list[IgnoreLine], source: str = ".dockerignore") -> None:
        self.source = source
        self.lines = list(lines)
        self.patterns: list[Pattern] = []
        for entry in lines:
            text = clean_path(entry.text.strip())
            exclusion = text.startswith("!")
            if exclusion:
                if len(text) == 1:
                    raise IgnoreSyntaxError(entry.number, "!", "illegal-exclusion")
                text = text[1:]
            if not _check_syntax(text):
                raise IgnoreSyntaxError(entry.number, text, "invalid-pattern")
            self.patterns.append(Pattern(text, entry.number, exclusion))

    def with_line(self, text: str) -> "Matcher":
        """A new matcher with one more line appended (used to verify a proposed fix)."""
        last = self.lines[-1].number if self.lines else 0
        return Matcher([*self.lines, IgnoreLine(last + 1, text)], self.source)

    def rule(self, index: int | None) -> Rule | None:
        if index is None:
            return None
        pattern = self.patterns[index]
        return Rule(self.source, pattern.line, pattern.display)

    def evaluate(self, path: str) -> Evaluation:
        """Run every line against ``path`` (slash-separated, relative to the context root)."""
        path = clean_path(path)
        result = Evaluation()
        if path == ".":
            return result
        parent = posixpath.dirname(path)
        parts = parent.split("/") if parent else []
        parents = ["/".join(parts[: k + 1]) for k in range(len(parts))]
        # 설명·힌트용: 경로 자신이나 상위 폴더 중 하나에 맞는 줄 전부
        for index, pat in enumerate(self.patterns):
            if pat.matches(path) or any(pat.matches(q) for q in parents):
                result.matched.append(index)
        # 판정: 빌더(BuildKit 의 컨텍스트 전송)처럼 맨 위 폴더부터 한 단계씩 내려가며, 각 줄이 상위 폴더에서
        # 맞았는지를 물려받는다. 상위 폴더에서 판정을 바꿀 수 없어 건너뛴 줄은 '맞지 않음'으로 물려진다.
        hits: list[bool] | None = None
        for step in [*parents, path]:
            state, hits, flips, deciding = self._step(step, hits)
        result.excluded = state
        result.flips = flips
        result.deciding = deciding
        # 설명용(판정에는 쓰지 않음): 경로 자신에는 맞지 않고 상위 폴더로만 맞는데 끝내 적용되지 않은 줄은,
        # 그 폴더에서 판정을 바꿀 수 없어 건너뛰어진 줄이다. 그 줄은 이 경로까지 내려오지 않는다.
        # 닿았다면 이 경로의 그 시점 판정을 바꿨을 줄만 고른다(아니면 '이미 같은 판정'이 맞는 설명이다).
        assert hits is not None
        for index in result.matched:
            pat = self.patterns[index]
            if hits[index] or pat.matches(path):
                continue
            # 이 경로 단계에서 이 줄 직전의 판정: 처음엔 포함, 뒤집힐 때마다 바뀐다
            before = sum(1 for f in flips if f < index) % 2 == 1
            if before != (not pat.exclusion):
                result.folder_skipped[index] = next(q for q in parents if pat.matches(q))
        return result

    def _step(self, path: str, parent_hits: list[bool] | None) -> tuple[bool, list[bool], list[int], int | None]:
        """One level of the builder's walk: (excluded, per-line hits handed to children, flips, deciding)."""
        hits = [False] * len(self.patterns)
        state = False
        flips: list[int] = []
        deciding: int | None = None
        for index, pat in enumerate(self.patterns):
            hit = parent_hits[index] if parent_hits else False
            if not hit:
                # A normal line can only exclude, an exception can only re-include: a line that cannot change the
                # current verdict is not even tried, and its slot stays False for the children (Docker does the same).
                if pat.exclusion != state:
                    continue
                hit = pat.matches(path)
            hits[index] = hit
            if hit and state != (not pat.exclusion):
                state = not pat.exclusion
                flips.append(index)
                deciding = index
        return state, hits, flips, deciding

    def decide(self, path: str) -> tuple[bool, Rule | None]:
        ev = self.evaluate(path)
        return ev.excluded, self.rule(ev.deciding)

    def anchored_hint(self, index: int, path: str) -> str | None:
        """Shortest prefix of ``path`` that ``**/<pattern>`` would match but the line itself does not."""
        pat = self.patterns[index]
        if pat.exclusion or pat.text.startswith("**") or pat.text == ".":
            return None
        wide = Pattern("**/" + pat.text, pat.line, False)
        pieces = path.split("/")
        for k in range(1, len(pieces) + 1):
            prefix = "/".join(pieces[:k])
            if wide.matches(prefix) and not pat.matches(prefix):
                # the line must not already cover this path through any shorter or equal prefix
                if not any(pat.matches("/".join(pieces[:j])) for j in range(1, len(pieces) + 1)):
                    return prefix
        return None
