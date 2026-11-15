"""AC-1: reading rules, matching meaning and syntax errors of the ignore-file matcher.

Every case is written for this project from the documented behaviour of the Docker CLI
(root anchoring, parent match, last match wins); no table is copied from another code base.
"""
from __future__ import annotations

import pytest

from _matcher import IgnoreLine, IgnoreSyntaxError, Matcher, clean_path, read_ignore_lines


def matcher(*patterns: str) -> Matcher:
    return Matcher([IgnoreLine(i + 1, p) for i, p in enumerate(patterns)])


# (patterns, path, excluded?) — grouped by the behaviour they pin down.
CASES: list[tuple[tuple[str, ...], str, bool]] = [
    # root anchoring: a pattern without a slash only matches at the context root
    (("*.md",), "a.md", True),
    (("*.md",), "docs/a.md", False),
    (("*.md",), "a.txt", False),
    (("docs",), "x/docs/a.md", False),
    (("*/temp*",), "x/temp1", True),
    (("*/temp*",), "x/y/temp1", False),
    (("*/*/temp*",), "a/b/temp.txt", True),
    (("*/*/temp*",), "a/temp.txt", False),
    # a match on any parent directory counts
    (("docs",), "docs/a.md", True),
    (("docs",), "docs/deep/er/a.md", True),
    (("docs/",), "docs/a.md", True),
    (("*",), "x", True),
    (("*",), "a/b", True),
    (("a*",), "a/b", True),
    (("*/temp*",), "x/temp1/file", True),
    # double star
    (("**/docs",), "x/docs/a.md", True),
    (("**/docs",), "docs/a.md", True),
    (("**/*.go",), "a/b/c.go", True),
    (("**/*.go",), "c.go", True),
    (("**/*.go",), "c.gox", False),
    (("dir/**",), "dir/a", True),
    (("dir/**",), "dir/a/b", True),
    (("dir/**",), "dir", False),
    (("a/**/b",), "a/b", True),
    (("a/**/b",), "a/x/y/b", True),
    (("a/**/b",), "a/x/c", False),
    (("**",), "a/b", True),
    # a double star glued to text is a suffix match, so it also hits `profile`
    (("**file",), "profile", True),
    (("**file",), "dir/profile", True),
    (("**file",), "file.txt", False),
    # single-segment wildcards never cross a slash
    (("?",), "a", True),
    (("?",), "ab", False),
    (("a?c",), "a/c", False),
    (("a?c",), "abc", True),
    (("a*c",), "abc", True),
    (("a*c",), "a/c", False),
    # character classes and escapes
    (("[ab].txt",), "a.txt", True),
    (("[ab].txt",), "c.txt", False),
    (("[^ab].txt",), "c.txt", True),
    (("[^ab].txt",), "a.txt", False),
    (("[a-c].txt",), "b.txt", True),
    ((r"[\]]",), "]", True),
    ((r"\*",), "*", True),
    ((r"\*",), "a", False),
    ((r"a\?b",), "a?b", True),
    # characters that are special for regular expressions stay literal
    (("a.b",), "axb", False),
    (("a.*",), "axb", False),
    (("a.*",), "a.b", True),
    (("a+b",), "a+b", True),
    (("a(b)",), "a(b)", True),
    (("a{b,c}",), "a{b,c}", True),
    (("a{b,c}",), "ab", False),
    (("$a",), "$a", True),
    # last matching line wins, exceptions re-include
    (("*.md", "!README.md"), "README.md", False),
    (("*.md", "!README.md"), "CHANGELOG.md", True),
    (("*.md", "!README*.md", "README-secret.md"), "README-secret.md", True),
    (("*.md", "!README*.md", "README-secret.md"), "README.md", False),
    (("*.md", "!README*.md", "README-secret.md"), "README-extra.md", False),
    (("!README.md", "*.md"), "README.md", True),
    (("*", "!keep"), "keep", False),
    (("*", "!keep"), "other", True),
    (("*", "!keep"), "dir/keep", True),
    (("a", "!a", "a"), "a", True),
    # an exception can re-include a file below an excluded directory
    (("docs", "!docs/a.md"), "docs/a.md", False),
    (("docs", "!docs/a.md"), "docs/b.md", True),
    (("docs/*", "!docs/a.md"), "docs/a.md", False),
    (("build", "!build/keep/x"), "build/keep/x", False),
    (("dist/*", "!dist/a.whl"), "dist/a.whl", False),
    (("dist/*", "!dist/a.whl"), "dist/b.whl", True),
    (("a/", "!a/b"), "a/b/c", False),
    # path cleaning
    (("a/b/../c",), "a/c", True),
    (("./a//b/",), "a/b/x", True),
    # letter case is compared as plain text on every platform
    (("secret.txt",), "secret.txt", True),
    (("secret.txt",), "Secret.txt", False),
    (("*.MD",), "a.md", False),
    (("README*",), "readme.md", False),
    # no patterns, nothing is excluded
    ((), "a", False),
]


def test_case_table_has_at_least_sixty_cases():
    assert len(CASES) >= 60


@pytest.mark.parametrize(("patterns", "path", "excluded"), CASES, ids=[f"{'|'.join(p)}::{x}" for p, x, _ in CASES])
def test_matching(patterns, path, excluded):
    assert matcher(*patterns).decide(path)[0] is excluded


# ---------------------------------------------------------------- reading rules

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# note\n*.md\n", [(2, "*.md")]),
        ("  # indented is a pattern\n", [(1, "# indented is a pattern")]),
        ("*.md   \n", [(1, "*.md")]),
        ("﻿*.md\n", [(1, "*.md")]),
        ("./a//b/\n", [(1, "a/b")]),
        ("/abs\n", [(1, "abs")]),
        ("!./keep\n", [(1, "!keep")]),
        ("! keep\n", [(1, "!keep")]),
        ("\n  \n\n", []),
        ("a\r\nb\r\n", [(1, "a"), (2, "b")]),
        ("a\n\n# c\nb\n", [(1, "a"), (4, "b")]),
    ],
)
def test_reading_rules(text, expected):
    assert [(line.number, line.text) for line in read_ignore_lines(text)] == expected


def test_leading_slash_from_a_file_is_removed_before_matching():
    m = Matcher(read_ignore_lines("/abs\n"))
    assert m.decide("abs/x")[0] is True
    assert m.decide("sub/abs/x")[0] is False


def test_clean_path():
    assert clean_path("") == "."
    assert clean_path("a/./b//c/") == "a/b/c"
    assert clean_path("a/../../b") == "../b"
    assert clean_path("/x/../y") == "/y"


# ---------------------------------------------------------------- syntax errors

@pytest.mark.parametrize("pattern", ["[]a]", "[-x]", "[a-b-c]", "a\\", "[", "[a", "[]", "x[^]"])
def test_invalid_patterns_are_rejected(pattern):
    with pytest.raises(IgnoreSyntaxError) as info:
        matcher("ok", pattern)
    assert info.value.line == 2
    assert info.value.kind == "invalid-pattern"


def test_lone_exclamation_mark_is_illegal():
    with pytest.raises(IgnoreSyntaxError) as info:
        matcher("a", "!")
    assert (info.value.line, info.value.kind) == (2, "illegal-exclusion")


@pytest.mark.parametrize("pattern", ["[a-b]", "[^a-b]", "[a-b]*", r"[\-]", "*", "a?"])
def test_valid_classes_are_accepted(pattern):
    matcher(pattern)


# ----------------------------------------------------------- decisions and lines

def test_decision_names_the_deciding_line():
    m = Matcher([IgnoreLine(2, "*.md"), IgnoreLine(3, "!README*.md"), IgnoreLine(4, "README-secret.md")])
    assert m.decide("a.md")[1].line == 2
    assert m.decide("README.md")[1].line == 3
    assert m.decide("README-secret.md")[1].line == 4
    assert m.decide("notes.txt")[1] is None


def test_a_skipped_line_does_not_become_the_deciding_line():
    m = matcher("a", "a")
    excluded, rule = m.decide("a")
    assert excluded is True and rule.line == 1


def test_evaluation_lists_matches_flips_and_decider():
    m = matcher("*.md", "!README*.md", "README-secret.md")
    ev = m.evaluate("README-secret.md")
    assert ev.matched == [0, 1, 2]
    assert ev.flips == [0, 1, 2]
    assert ev.deciding == 2 and ev.excluded is True
    ev = m.evaluate("README.md")
    assert ev.matched == [0, 1] and ev.deciding == 1 and ev.excluded is False


def test_with_line_appends_without_changing_the_original():
    m = matcher("*.md")
    m2 = m.with_line("!keep.md")
    assert len(m.patterns) == 1 and len(m2.patterns) == 2
    assert m2.patterns[-1].line == 2
    assert m2.decide("keep.md")[0] is False


def test_anchored_hint_finds_the_nested_path_and_ignores_covered_paths():
    m = matcher("node_modules")
    assert m.anchored_hint(0, "web/node_modules/react/index.js") == "web/node_modules"
    assert m.anchored_hint(0, "node_modules/x.js") is None
    assert matcher("**/node_modules").anchored_hint(0, "web/node_modules/a") is None
    assert matcher("!x").anchored_hint(0, "a/x") is None
