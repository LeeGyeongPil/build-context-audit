"""AC-9: the commands in README.md and README.ko.md run on the demo copy and show what the text says.

Rules: every fenced line that calls audit.py (except the install line with the CONTEXT placeholder)
runs with /tmp/bca-demo replaced by the test's demo copy; a trailing '| tail -N' window must start
at the section the option adds; the JSON key line names only real top-level keys; both READMEs have
the same number of '## ' sections.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

import setup_demo
from _i18n import t
from conftest import DEMO, REPO

READMES = {"en": REPO / "README.md", "ko": REPO / "README.ko.md"}
AUDIT = "skills/build-context-audit/scripts/audit.py"
SETUP = "demo/setup_demo.py"
PLACE = "/tmp/bca-demo"  # the folder the README uses; tests swap in their own copy
TAIL = re.compile(r"tail -(\d+)")


def fenced_lines(path: Path) -> list[str]:
    """Lines inside ``` fences."""
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line.strip())
    return lines


def outside_fences(path: Path) -> list[str]:
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif not inside:
            lines.append(line)
    return lines


def readme_commands(lang: str) -> list[str]:
    """The audit.py part of every runnable README line (the setup part of '&&' lines is dropped)."""
    found = []
    for line in fenced_lines(READMES[lang]):
        if AUDIT not in line or "CONTEXT" in line:
            continue  # the install section's 'audit.py CONTEXT' is a placeholder, not a demo command
        found.extend(part.strip() for part in line.split("&&") if AUDIT in part)
    return found


def split_command(command: str, demo: Path) -> tuple[list[str], int | None]:
    """'python3 audit.py ARGS | tail -N' -> (ARGS with the demo copy, N or None)."""
    tail_n = None
    if "|" in command:
        command, pipe = (part.strip() for part in command.split("|", 1))
        match = TAIL.fullmatch(pipe)
        assert match, f"only '| tail -N' is understood here: {pipe!r}"
        tail_n = int(match.group(1))
    argv = shlex.split(command.replace(PLACE, str(demo)))
    assert argv[:2] == ["python3", AUDIT], command
    return argv[2:], tail_n


def option_value(argv: list[str], name: str, default: str | None = None) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else default


CASES = [(lang, command) for lang in READMES for command in readme_commands(lang)]


def test_each_readme_has_the_demo_commands():
    en, ko = readme_commands("en"), readme_commands("ko")
    assert len(en) >= 5, en  # hero, explain, -f, suggest, compare
    assert [c.replace("--lang ko", "--lang en") for c in ko] == en  # only the language differs


@pytest.mark.parametrize(("lang", "command"), CASES, ids=[f"{lang}:{i}" for i, (lang, _) in enumerate(CASES)])
def test_readme_command_runs_and_its_tail_window_starts_at_the_section(cli, monkeypatch, lang, command):
    monkeypatch.chdir(REPO)  # README commands run from the repo root (demo/proposed.dockerignore is relative)
    argv, tail_n = split_command(command, DEMO)
    result = cli(*argv)
    assert result.code in (0, 1), result.err
    out_lang = option_value(argv, "--lang", "en")
    assert out_lang == lang
    lines = result.out.splitlines()
    if tail_n is None:
        return
    assert len(lines) >= tail_n, f"output has {len(lines)} lines, tail -{tail_n} would show all of it"
    window = lines[-tail_n:]
    report = cli(*argv, "--format", "json").json()
    if "--suggest" in argv:
        assert window[0] == t(lang, "suggest.header", file=report["suggestions"][0]["append_to"])
    elif "--compare-ignore" in argv:
        assert window[0] == t(lang, "compare.header", file=report["compare"]["file"])  # ko puts the file first
    elif "--explain" in argv:
        assert window[0].startswith(option_value(argv, "--explain") + ": ")
    else:
        pytest.fail(f"'| tail -{tail_n}' without --suggest, --compare-ignore or --explain: {command}")
    result_word = t(lang, "result.ok").split(":")[0]  # "Result" / "결과"
    assert window[-1].startswith(result_word + ":"), window[-1]  # the window ends at the Result: line


@pytest.mark.parametrize("lang", list(READMES))
def test_setup_part_of_the_first_command_can_be_run_twice(tmp_path, capsys, lang):
    lines = [line for line in fenced_lines(READMES[lang]) if SETUP in line]
    assert lines, "the first demo command prepares the copy with setup_demo.py"
    dest = tmp_path / "bca-demo"
    for line in lines:
        setup = shlex.split(next(p for p in line.split("&&") if SETUP in p).replace(PLACE, str(dest)))
        assert setup[:2] == ["python3", SETUP]
        assert setup_demo.main(setup[2:], env={"LANG": "C"}) == 0
        assert setup_demo.main(setup[2:], env={"LANG": "C"}) == 0  # re-running the README line works
        assert capsys.readouterr().out == f"{dest}\n{dest}\n"
    assert (dest / ".env").is_file()


@pytest.mark.parametrize("lang", list(READMES))
def test_json_key_line_names_real_top_level_keys(cli, monkeypatch, lang):
    monkeypatch.chdir(REPO)
    lines = [
        line
        for line in READMES[lang].read_text(encoding="utf-8").splitlines()
        if ("JSON (" in line or "JSON(" in line) and "--format json" in line
    ]
    assert lines, "the options paragraph lists the JSON top-level keys"
    keys = {key for line in lines for key in re.findall(r"`([a-z_]+)`", line)}
    assert len(keys) >= 10, keys
    report = cli(
        str(DEMO), "--format", "json", "--list", "all", "--suggest",
        "--compare-ignore", "demo/proposed.dockerignore", "--explain", "README-secret.md",
    ).json()
    assert keys - set(report) == set()


def test_both_readmes_have_the_same_number_of_sections():
    counts = {lang: sum(line.startswith("## ") for line in outside_fences(path)) for lang, path in READMES.items()}
    assert counts["en"] == counts["ko"], counts
