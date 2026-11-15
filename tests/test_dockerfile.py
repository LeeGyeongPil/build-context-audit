"""COPY and ADD parsing boundaries and how sources are judged against a context."""
from __future__ import annotations

import pytest

from _dockerfile import parse


def one(text: str):
    ins = parse(text).instructions
    assert len(ins) == 1, ins
    return ins[0]


def test_plain_copy_and_line_number():
    ins = one("FROM scratch\n\nCOPY a.txt b/ /dest/\n")
    assert (ins.line, ins.keyword, ins.sources, ins.dest) == (3, "COPY", ["a.txt", "b/"], "/dest/")


def test_keyword_is_case_insensitive():
    assert one("copy a /b\n").keyword == "COPY"


def test_line_continuation_keeps_first_line_number():
    ins = one("FROM scratch\nCOPY a.txt \\\n   /a.txt\n")
    assert ins.line == 2 and ins.sources == ["a.txt"] and ins.dest == "/a.txt"


def test_comment_and_blank_lines_inside_a_continuation_are_dropped():
    ins = one("COPY a \\\n# note\n\n b \\\n /dest/\n")
    assert ins.sources == ["a", "b"] and ins.dest == "/dest/"


def test_json_array_form():
    assert one('COPY ["my file.txt", "/dest/"]\n').sources == ["my file.txt"]


def test_broken_json_falls_back_to_words():
    ins = one("COPY [a /b\n")
    assert ins.sources and ins.dest == "/b"


def test_flags_are_separated_from_sources():
    ins = one("COPY --chown=1:1 --chmod=644 --link a.txt /a\n")
    assert ins.flags == ["--chown=1:1", "--chmod=644", "--link"] and ins.sources == ["a.txt"] and ins.skip is None


def test_from_flag_is_skipped():
    ins = one("COPY --from=build /out /app\n")
    assert ins.skip == "from" and ins.sources == ["/out"]


def test_heredoc_is_skipped_and_its_body_is_not_parsed():
    parsed = parse("COPY <<EOF /file\nCOPY inside body /x\nEOF\nCOPY a /b\n")
    assert [(i.line, i.skip) for i in parsed.instructions] == [(1, "heredoc"), (4, None)]


def test_run_heredoc_body_is_not_parsed():
    parsed = parse("RUN <<-EOT\n\tCOPY fake /x\n\tEOT\nCOPY real /y\n")
    assert [i.sources for i in parsed.instructions] == [["real"]]


def test_single_argument_is_unparsable():
    assert one("COPY onlyone\n").skip == "unparsable"


def test_other_instructions_are_ignored():
    assert parse("FROM x\nRUN echo COPY a b\nENV A=1\n").instructions == []


def test_escape_directive_is_reported_only_at_the_top():
    assert parse("# escape=`\nFROM x\n").escape_directive_line == 1
    assert parse("FROM x\n# escape=`\n").escape_directive_line is None


def test_bom_on_first_line():
    assert one("﻿COPY a /b\n").line == 1


def test_trailing_backslash_at_end_of_file():
    assert one("COPY a /b \\").sources == ["a"]


def test_quoted_source_with_space():
    assert one('COPY "my file" /d\n').sources == ["my file"]


def audit(cli, make_ctx, files, *args):
    ctx = make_ctx(files)
    result = cli(str(ctx), "--format", "json", *args)
    return result, {c["source"]: c for c in result.json()["copy_checks"]}


def test_directory_source_is_ok_when_one_file_survives(cli, make_ctx):
    _, checks = audit(
        cli, make_ctx,
        {"Dockerfile": "COPY app /app\n", ".dockerignore": "app/*.tmp\n", "app/a.py": "x", "app/b.tmp": "y"},
    )
    assert checks["app"]["status"] == "ok"


def test_directory_source_is_excluded_when_everything_in_it_is(cli, make_ctx):
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY app/ /app\n", ".dockerignore": "app\n", "app/a.py": "x"})
    assert checks["app/"]["status"] == "excluded"
    assert checks["app/"]["rule"]["line"] == 1


def test_missing_source_and_letter_case(cli, make_ctx):
    result, checks = audit(cli, make_ctx, {"Dockerfile": "COPY Readme.md /r\nCOPY nothing /n\n", "README.md": "x"})
    assert checks["Readme.md"]["status"] == "missing" and checks["nothing"]["status"] == "missing"
    assert result.code == 1


def test_wildcard_sources(cli, make_ctx):
    _, checks = audit(
        cli, make_ctx,
        {"Dockerfile": "COPY docs/*.md /d/\nCOPY src/*.go /s/\nCOPY nomatch*.x /n/\n",
         ".dockerignore": "src\n", "docs/a.md": "x", "src/a.go": "y"},
    )
    assert checks["docs/*.md"]["status"] == "ok"
    assert checks["src/*.go"]["status"] == "excluded" and checks["src/*.go"]["rule"]["pattern"] == "src"
    assert checks["nomatch*.x"]["status"] == "missing"


def test_dot_source_copies_the_whole_context(cli, make_ctx):
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY . /app\n", "a.txt": "x"})
    assert checks["."]["status"] == "ok"
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY . /app\n", ".dockerignore": "*\n!Dockerfile.nothing\n", "a.txt": "x"})
    assert checks["."]["status"] == "excluded"


def test_absolute_and_dotted_sources_are_relative_to_the_context(cli, make_ctx):
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY /a.txt ./b.txt ./dir/../a.txt /d/\n", "a.txt": "x", "b.txt": "y"})
    assert {c["status"] for c in checks.values()} == {"ok"}


def test_source_that_leaves_the_context_is_missing(cli, make_ctx):
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY ../secret /d\n", "a.txt": "x"})
    assert checks["../secret"]["status"] == "missing" and checks["../secret"]["note"] == "outside-context"


def test_variable_sources_are_reported_as_dynamic(cli, make_ctx):
    result, checks = audit(cli, make_ctx, {"Dockerfile": "ARG F=a\nCOPY ${F}.txt /d\n", "a.txt": "x"})
    assert checks["${F}.txt"]["status"] == "dynamic"
    assert result.code == 0


def test_dynamic_counts_as_warning_only(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY $F /d\n", "a.txt": "x"})
    assert cli(str(ctx), "--fail-on", "warning").code == 1
    assert cli(str(ctx)).code == 0


def test_add_url_and_git_sources_are_skipped(cli, make_ctx):
    _, checks = audit(
        cli, make_ctx,
        {"Dockerfile": "ADD https://example.com/x.tgz /t\nADD git@github.com:o/r.git /r\nADD local.tgz /l\n", "local.tgz": "x"},
    )
    assert checks["https://example.com/x.tgz"]["status"] == "skipped"
    assert checks["git@github.com:o/r.git"]["note"] == "remote"
    assert checks["local.tgz"]["status"] == "ok"


def test_heredoc_instruction_is_listed_as_skipped(cli, make_ctx):
    _, checks = audit(cli, make_ctx, {"Dockerfile": "COPY <<EOF /f\nhello\nEOF\n"})
    assert checks["(heredoc)"]["note"] == "heredoc"


@pytest.mark.parametrize("name", ["Dockerfile"])
def test_context_without_dockerfile_skips_the_copy_check(cli, make_ctx, name):
    ctx = make_ctx({"a.txt": "x"})
    result = cli(str(ctx))
    assert result.code == 0 and "COPY/ADD check is skipped" in result.out
    rep = cli(str(ctx), "--format", "json").json()
    assert rep["dockerfile"] is None and rep["copy_checks"] == []
