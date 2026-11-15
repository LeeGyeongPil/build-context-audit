"""AC-9: shape of the evaluation set, and every exact-value grader really matches the script's output."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import audit
from conftest import REPO

EVALS = REPO / "evals"
FIXTURES = EVALS / "fixtures"
CASES = sorted(d for d in EVALS.iterdir() if d.is_dir() and d.name != "fixtures")

# how an agent would run the script in each task's working folder (the fixture folder); --lang is added per test
TASK_ARGS = {
    "task-context-total": ["."],
    "task-deciding-lines": [
        ".",
        "--explain", "release",
        "--explain", "docs/api/openapi.yaml",
        "--explain", "notes.bak",
        "--explain", "config/app.yaml",
    ],
    "task-error-syntax": ["."],
    "task-compare": [".", "--compare-ignore", "proposed.dockerignore"],
    "task-dockerfile-specific": [".", "-f", "docker/api.Dockerfile"],
    "task-secrets": ["."],
}

# An answer written from the script's output: every answer grader must accept it.
GOOD_ANSWERS = {
    "task-context-total": "The build sends **7 files, 7,665 B**. The largest first-level folder is `src` with 4652 B.",
    "task-deciding-lines": (
        "release: EXCLUDED, line 4\n"
        "`docs/api/openapi.yaml`: **INCLUDED**, line 3\n"
        "notes.bak: INCLUDED, line none\n"
        "config/app.yaml: EXCLUDED, line 8\n"
    ),
    "task-error-syntax": "No. The builder rejects line 6, `[-_]tmp*`: invalid pattern (syntax error in pattern).",
    "task-compare": (
        "Now 19880 B, with the proposal 9,110 B: 10770 bytes smaller.\n"
        "Dockerfile:3 COPY requirements.txt: ok -> EXCLUDED; COPY app and COPY assets/fonts stay ok."
    ),
    "task-dockerfile-specific": (
        "It uses docker/api.Dockerfile.dockerignore and sends 5 files, 8750 B.\n"
        "COPY proto fails: excluded by docker/api.Dockerfile.dockerignore:2 '*'. The other COPY lines are ok."
    ),
    "task-secrets": (
        "SENT: certs/server.pem - add **/*.pem\n"
        "SENT: certs/tls.key - add **/*.key at the end (line 10 '!certs' re-includes it)\n"
        "- SENT: `deploy/id_rsa` - add **/id_rsa\n"
        "SENT: infra/terraform.tfstate - add **/*.tfstate\n"
        "SENT: kubeconfig - add kubeconfig (on its own line, without the trailing comment)\n"
        "(checked by file name, not content)"
    ),
}

# The answer careful hand reasoning gives when it knows Docker's root anchoring and re-includes but reads
# the ignore file like a shell or gitignore user would: '#' starts a comment anywhere, '[!x]' negates,
# a trailing '/' means folders only. The fixtures are built so that each such slip moves an exact value.
GITIGNORE_HABIT_ANSWERS = {
    "task-context-total": "It sends 9 files, 7,913 bytes; the largest folder is src with 4,652 bytes.",
    "task-deciding-lines": (
        "release: INCLUDED, line none\n"
        "docs/api/openapi.yaml: INCLUDED, line 3\n"
        "notes.bak: EXCLUDED, line 5\n"
        "config/app.yaml: EXCLUDED, line 8\n"
    ),
    "task-error-syntax": "Yes, every line is valid and the builder accepts the file; line 4 [!.]cache negates the dot.",
    "task-compare": (
        "Now 19,880 bytes, with the proposal 5,010 bytes (14,870 bytes smaller).\n"
        "No COPY line changes status: requirements.txt is kept by [!r]*.txt."
    ),
    "task-dockerfile-specific": (
        "It uses docker/api.Dockerfile.dockerignore and sends 4 files, 4,429 bytes.\n"
        "COPY proto fails because of line 2 '*'."
    ),
    "task-secrets": (
        "SENT: certs/server.pem - add **/*.pem\n"
        "SENT: deploy/id_rsa - add **/id_rsa\n"
        "SENT: infra/terraform.tfstate - add **/*.tfstate\n"
    ),
}

# Names that copy tools commonly skip. Round 4's evaluation copied fixtures without node_modules, so totals
# measured in the evaluation workspace no longer matched the graders. Fixtures must not rely on such names.
COPY_SKIPPED_NAMES = {
    "node_modules", "build", "dist", "tmp", "temp", "logs", "out", "target", "coverage", "vendor",
    "__pycache__", "venv", "env", "site-packages", "bower_components", "Thumbs.db",
}
COPY_SKIPPED_SUFFIXES = (".log", ".pyc", ".pyo", ".tmp", ".swp", ".egg-info")


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    block = text.split("---\n", 2)[1]
    data = {}
    for line in block.splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        data[key.strip()] = value
    return data


def names(prefix: str) -> list[Path]:
    return [c for c in CASES if c.name.startswith(prefix)]


def prompt_text(case: Path) -> str:
    return case.joinpath("prompt.md").read_text(encoding="utf-8").split("---\n", 2)[2].strip()


def test_counts():
    triggers = names("trigger-")
    notrigger = names("notrigger-")
    near = names("notrigger-near-")
    tasks = names("task-")
    assert len(triggers) >= 10
    assert sum(1 for c in triggers if re.search("[가-힣]", prompt_text(c))) >= 2
    assert len(notrigger) >= 10 and len(near) >= 5
    assert len(tasks) >= 5 and any(c.name.startswith("task-error-") for c in tasks)


def test_trigger_prompts_do_not_name_the_skill():
    for case in names("trigger-"):
        text = prompt_text(case)
        assert not re.search(r"build-context-audit|\bskill\b|스킬", text, re.I), case.name


def test_every_case_has_prompt_and_graders():
    for case in CASES:
        assert (case / "prompt.md").is_file(), case.name
        assert list((case / "graders").glob("*.md")), case.name
        fm = frontmatter(case / "prompt.md")
        assert fm["name"] == case.name


def test_skill_graders():
    for case in names("trigger-"):
        g = frontmatter(case / "graders" / "skill-fired.md")
        assert g["tool"] == "Skill" and g["arm"] == "both"
        assert re.search(g["input_match"], '{"skill": "build-context-audit"}')
        assert re.search(g["input_match"], '{"skill":"build-context-audit:build-context-audit"}')
        assert not re.search(g["input_match"], '{"skill": "pdf"}')
    for case in names("notrigger-"):
        g = frontmatter(case / "graders" / "skill-not-fired.md")
        assert (g["tool"], g["min"], g["max"], g["arm"]) == ("Skill", "0", "0", "both")


def test_every_task_has_a_fixture_and_an_exact_value_grader():
    for case in names("task-"):
        assert (FIXTURES / case.name).is_dir(), case.name
        ran = frontmatter(case / "graders" / "script-ran.md")
        assert ran["arm"] == "with-only" and "scripts/audit" in ran["input_match"]
        regexes = [
            frontmatter(p) for p in (case / "graders").glob("*.md") if frontmatter(p)["type"] == "regex"
        ]
        assert any(g.get("target") == "trace" for g in regexes), case.name
        assert all(len(g["pattern"]) >= 6 for g in regexes), case.name
    assert set(TASK_ARGS) == {c.name for c in names("task-")}


def test_fixtures_hold_no_dot_files_and_are_small():
    for path in FIXTURES.rglob("*"):
        assert not any(part.startswith(".") for part in path.relative_to(FIXTURES).parts), path
    assert sum(p.stat().st_size for p in FIXTURES.rglob("*") if p.is_file()) < 200_000


def test_fixtures_avoid_names_that_copy_tools_skip():
    for path in FIXTURES.rglob("*"):
        for part in path.relative_to(FIXTURES).parts:
            assert part not in COPY_SKIPPED_NAMES, path
            assert not part.endswith(COPY_SKIPPED_SUFFIXES), path


def regex_graders(task: str, target: str | None) -> list[tuple[str, re.Pattern[str]]]:
    found = []
    for path in sorted((EVALS / task / "graders").glob("*.md")):
        g = frontmatter(path)
        if g["type"] == "regex" and g.get("target") == target:
            flags = re.I if "i" in str(g.get("flags") or "") else 0
            found.append((path.name, re.compile(g["pattern"], flags)))
    return found


@pytest.mark.parametrize("lang", ["en", "ko"])
@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_trace_graders_match_the_real_script_output(task, lang, capsys, monkeypatch):
    """The graders were written from real runs; they must hold in both output languages,
    because the evaluation machine's locale decides the language when --lang is not given."""
    monkeypatch.chdir(FIXTURES / task)
    code = audit.main([*TASK_ARGS[task], "--lang", lang])
    captured = capsys.readouterr()
    trace = captured.out + captured.err
    assert code in (0, 1, 3)
    traced = regex_graders(task, "trace")
    assert traced, task
    for name, rx in traced:
        assert rx.search(trace), f"{task}/{name} does not match ({lang}):\n{trace}"
    if lang == "en":
        # exact-value answer graders (case-sensitive) must also be facts the script prints
        for name, rx in regex_graders(task, None):
            # answer-count-* graders check the reply format (how many SENT lines), not a printed fact
            if not rx.flags & re.I and not name.startswith("answer-count-"):
                assert rx.search(trace), f"{task}/{name} not in output:\n{trace}"


@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_answer_graders_accept_an_answer_copied_from_the_script(task):
    for name, rx in regex_graders(task, None):
        assert rx.search(GOOD_ANSWERS[task]), f"{task}/{name} rejects the good answer"


@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_answer_graders_reject_the_gitignore_habit_answer(task):
    """One misread rule must cost at least two answer graders, so a case cannot pass without the script."""
    graders = regex_graders(task, None)
    failed = [name for name, rx in graders if not rx.search(GITIGNORE_HABIT_ANSWERS[task])]
    assert len(failed) >= 2, f"{task}: the hand-reasoned answer fails only {failed}"


def test_every_task_has_both_reference_answers():
    assert set(GOOD_ANSWERS) == set(GITIGNORE_HABIT_ANSWERS) == set(TASK_ARGS)


def test_task_prompts_ask_for_exact_values_and_forbid_edits():
    for case in names("task-"):
        text = prompt_text(case)
        assert "Do not edit any file." in text, case.name
        assert not re.search(r"build-context-audit|\bskill\b|audit\.py", text, re.I), case.name


def test_grader_patterns_are_javascript_safe():
    for path in EVALS.glob("*/graders/*.md"):
        g = frontmatter(path)
        pattern = g.get("pattern") or g.get("input_match") or ""
        assert not re.search(r"\(\?P[<=]|\\[AZ]\b|\\\\[sSdDwWbB]", pattern), path
        re.compile(pattern)


@pytest.mark.parametrize(
    "task", ["task-context-total", "task-compare", "task-dockerfile-specific", "task-error-syntax"]
)
def test_script_output_pasted_as_the_answer_passes_every_answer_grader(task, capsys, monkeypatch):
    """An agent that pastes the printed report (a code block) instead of rephrasing it must not lose points.
    (Per-path cases ask for their own reply format, so they are covered by GOOD_ANSWERS instead.)"""
    monkeypatch.chdir(FIXTURES / task)
    audit.main([*TASK_ARGS[task], "--lang", "en"])
    captured = capsys.readouterr()
    pasted = captured.out + captured.err
    for name, rx in regex_graders(task, None):
        assert rx.search(pasted), f"{task}/{name} rejects the pasted report:\n{pasted}"
