"""AC-6: exit codes and error lines."""
from __future__ import annotations

import pytest

import audit
from conftest import DEMO


def test_missing_context_is_exit_2(cli, tmp_path):
    result = cli(str(tmp_path / "nope"))
    assert result.code == 2
    assert result.err.startswith("error: context directory not found: ")
    assert "fix:" in result.err and result.out == ""


def test_context_that_is_a_file_is_exit_2(cli, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert cli(str(f)).code == 2


def test_missing_explicit_dockerfile_is_exit_2(cli, make_ctx):
    ctx = make_ctx({"a.txt": "x"})
    result = cli(str(ctx), "-f", "nope.Dockerfile")
    assert result.code == 2 and result.err.startswith("error: Dockerfile not found: nope.Dockerfile")


def test_dockerfile_is_also_looked_up_inside_the_context(cli, make_ctx):
    ctx = make_ctx({"build.Dockerfile": "COPY a.txt /a\n", "a.txt": "x"})
    assert cli(str(ctx), "-f", "build.Dockerfile", "--format", "json").json()["dockerfile"] == "build.Dockerfile"


def test_missing_explicit_ignore_file_is_exit_2(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n"})
    result = cli(str(ctx), "--ignore-file", str(ctx / "none.ignore"))
    assert result.code == 2 and result.err.startswith("error: cannot read ")


def test_ignore_file_that_is_not_utf8_is_exit_2(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n"})
    (ctx / ".dockerignore").write_bytes(b"\xff\xfe\x00bad")
    result = cli(str(ctx))
    assert result.code == 2 and "error: cannot read" in result.err


def test_bad_pattern_on_line_three_is_exit_3(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".dockerignore": "*.md\n# c\n[]a]\n"})
    result = cli(str(ctx))
    assert result.code == 3
    assert result.err.splitlines()[0] == "error: .dockerignore:3: invalid pattern '[]a]': syntax error in pattern"
    assert result.out == ""


def test_lone_exclamation_mark_is_exit_3(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".dockerignore": "a\n!\n"})
    result = cli(str(ctx))
    assert result.code == 3 and 'illegal exclusion pattern: "!"' in result.err
    assert result.err.startswith("error: .dockerignore:2:")


def test_syntax_error_in_dockerfile_specific_file_names_that_file(cli, make_ctx):
    ctx = make_ctx({"build.Dockerfile": "FROM scratch\n", "build.Dockerfile.dockerignore": "[\n"})
    result = cli(str(ctx), "-f", str(ctx / "build.Dockerfile"))
    assert result.code == 3 and "build.Dockerfile.dockerignore:1" in result.err


def test_clean_context_is_exit_0(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY a.txt /a\n", ".dockerignore": "*.log\n", "a.txt": "x"})
    result = cli(str(ctx))
    assert result.code == 0
    assert "Result: no COPY/ADD problem and no secret-looking file." in result.out


def test_fail_on_never_hides_findings_from_the_exit_code(cli):
    assert cli(str(DEMO), "--fail-on", "never").code == 0
    assert cli(str(DEMO), "--fail-on", "never", "--format", "json").json()["summary"]["copy_problems"] == 2


def test_fail_on_warning_flags_hints_on_an_otherwise_clean_context(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY a.txt /a\n", ".dockerignore": "nothing-here\n", "a.txt": "x"})
    assert cli(str(ctx)).code == 0
    assert cli(str(ctx), "--fail-on", "warning").code == 1


def test_syntax_error_wins_over_fail_on_never(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".dockerignore": "[\n"})
    assert cli(str(ctx), "--fail-on", "never").code == 3


def test_unwritable_out_path_is_exit_2(cli, tmp_path):
    result = cli(str(DEMO), "--out", str(tmp_path / "missing-dir" / "r.txt"))
    assert result.code == 2 and result.err.startswith("error: cannot write ")


def test_argparse_errors_exit_2(cli):
    with pytest.raises(SystemExit) as info:
        cli()
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        cli(str(DEMO), "--format", "xml")
    assert info.value.code == 2


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as info:
        audit.main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.startswith("build-context-audit ")


def test_unreadable_folder_becomes_a_note_not_a_crash(cli, make_ctx):
    import os

    ctx = make_ctx({"Dockerfile": "FROM scratch\n", "locked/a.txt": "x", "ok.txt": "y"})
    os.chmod(ctx / "locked", 0)
    try:
        result = cli(str(ctx), "--format", "json")
    finally:
        os.chmod(ctx / "locked", 0o755)
    notes = result.json()["notes"]
    if notes:  # running as an account that can read everything leaves no note
        assert notes[0]["code"] == "unreadable"
    assert result.code == 0


def test_missing_source_text_explains_the_likely_cause(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY Readme.md /r\n", "README.md": "x"})
    result = cli(str(ctx))
    assert "MISSING" in result.out and "check the path and its letter case" in result.out
    assert result.code == 1
