"""AC-9: the task graders must notice a wrong script (mutation check of the evaluation set).

The evaluation swaps the bundled script for a mutant and re-runs each task case. A case must then
fail (score below 0.67) whenever the mutant prints a wrong value for that case, even if the agent
works the right answer out by hand next to the wrong output. Here each mutant is a small, realistic
bug patched into the script in-process; the case score is computed the way the evaluator does it:
passed graders / all graders, with ``script-ran`` counted as passed (the mutant still runs).
"""
from __future__ import annotations

import re

import pytest

import _matcher
import _report
import audit
from _matcher import IgnoreLine
from test_evals_shape import FIXTURES, GITIGNORE_HABIT_ANSWERS, GOOD_ANSWERS, TASK_ARGS, regex_graders

PASS_SCORE = 0.67
# total-type cases where an agent may paste the report as its answer
PASTED_TASKS = ("task-context-total", "task-compare", "task-dockerfile-specific", "task-error-syntax")


# ------------------------------------------------------------------ mutants
# Each function patches one bug into the script with pytest's monkeypatch.

def verdict_flip(mp):
    """Rule verdict inverted: excluded files are sent and sent files are excluded."""
    orig = _matcher.Matcher.evaluate

    def evaluate(self, path):
        ev = orig(self, path)
        ev.excluded = not ev.excluded
        return ev

    mp.setattr(_matcher.Matcher, "evaluate", evaluate)


def first_match_wins(mp):
    """The first matching line decides instead of the last one."""
    orig = _matcher.Matcher.evaluate

    def evaluate(self, path):
        ev = orig(self, path)
        if ev.matched:
            first = ev.matched[0]
            ev.excluded = not self.patterns[first].exclusion
            ev.deciding = first
        return ev

    mp.setattr(_matcher.Matcher, "evaluate", evaluate)


def any_depth(mp):
    """Patterns match at any depth, like .gitignore (no root anchoring)."""
    orig = _matcher.Pattern.matches

    def matches(self, path):
        parts = path.split("/")
        return any(orig(self, "/".join(parts[k:])) for k in range(len(parts)))

    mp.setattr(_matcher.Pattern, "matches", matches)


def _rewrite_lines(mp, change):
    orig = audit.read_lines
    mp.setattr(audit, "read_lines", lambda path: [change(line) for line in orig(path)])


def line_plus_one(mp):
    """Ignore-file line numbers off by one."""
    _rewrite_lines(mp, lambda line: IgnoreLine(line.number + 1, line.text))


def inline_comment_stripped(mp):
    """'#' after a pattern read as a comment (shell / gitignore habit)."""
    _rewrite_lines(mp, lambda line: IgnoreLine(line.number, re.sub(r"\s+#.*$", "", line.text)))


def bang_negates(mp):
    """'[!x]' read as a negated class."""
    _rewrite_lines(mp, lambda line: IgnoreLine(line.number, line.text.replace("[!", "[^")))


def syntax_check_off(mp):
    """Bad patterns accepted."""
    mp.setattr(_matcher, "_check_syntax", lambda pattern: True)


def root_ignore_only(mp):
    """<Dockerfile>.dockerignore not preferred: only the root .dockerignore is read."""
    orig = audit.choose
    mp.setattr(audit, "choose", lambda ctx, dockerfile, explicit: orig(ctx, dockerfile.with_name("-"), explicit))


def _wrap_totals(mp, key, delta):
    orig = audit.totals

    def totals(results):
        out = orig(results)
        out[key] += delta
        return out

    mp.setattr(audit, "totals", totals)


def count_plus_one(mp):
    _wrap_totals(mp, "included_files", 1)


def count_minus_one(mp):
    _wrap_totals(mp, "included_files", -1)


def bytes_plus_one(mp):
    _wrap_totals(mp, "included_bytes", 1)


def top_folder_bytes(mp):
    """Largest-folder bytes off by one."""
    orig = audit.top_dirs

    def top_dirs(results, limit):
        rows = orig(results, limit)
        if rows:
            rows[0]["bytes"] += 1
        return rows

    mp.setattr(audit, "top_dirs", top_dirs)


def copy_flip(mp):
    """COPY verdict ok and EXCLUDED swapped."""
    orig = audit.check_copies
    swap = {"ok": "excluded", "excluded": "ok"}

    def check_copies(*args):
        rows = orig(*args)
        for row in rows:
            row["status"] = swap.get(row["status"], row["status"])
        return rows

    mp.setattr(audit, "check_copies", check_copies)


def secret_missed(mp):
    """One kind of secret name (kubeconfig) not recognised."""
    orig = _report.secret_kind
    mp.setattr(_report, "secret_kind", lambda path: None if path.endswith("kubeconfig") else orig(path))


def compare_delta_off(mp):
    """What-if byte change off by one."""
    orig = audit.compare

    def compare(*args):
        out = orig(*args)
        out["bytes_delta"] += 1
        return out

    mp.setattr(audit, "compare", compare)


MUTANTS = {
    f.__name__: f
    for f in (
        verdict_flip, first_match_wins, any_depth, line_plus_one, inline_comment_stripped, bang_negates,
        syntax_check_off, root_ignore_only, count_plus_one, count_minus_one, bytes_plus_one, top_folder_bytes,
        copy_flip, secret_missed, compare_delta_off,
    )
}


# ------------------------------------------------------------------ scoring

def run_script(task: str, capsys, monkeypatch) -> str:
    monkeypatch.chdir(FIXTURES / task)
    try:
        audit.main([*TASK_ARGS[task], "--lang", "en"])
        crash = ""
    except Exception as exc:  # a mutant may crash the script; the agent then sees a traceback
        crash = f"Traceback (most recent call last):\n{type(exc).__name__}: {exc}\n"
    captured = capsys.readouterr()
    return captured.out + captured.err + crash


def score(task: str, trace: str, answer: str) -> float:
    """Evaluator arithmetic: script-ran (passed) + answer graders on the reply + trace graders on the trace."""
    answers = regex_graders(task, None)
    traces = regex_graders(task, "trace")
    passed = 1 + sum(bool(rx.search(answer)) for _, rx in answers) + sum(bool(rx.search(trace)) for _, rx in traces)
    return passed / (1 + len(answers) + len(traces))


def mutated_trace(task: str, mutant: str, capsys, monkeypatch) -> str:
    with monkeypatch.context() as mp:
        MUTANTS[mutant](mp)
        return run_script(task, capsys, mp)


# ------------------------------------------------------------------ tests

@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_real_script_and_good_answer_score_full(task, capsys, monkeypatch):
    assert score(task, run_script(task, capsys, monkeypatch), GOOD_ANSWERS[task]) == 1.0


@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_answers_without_the_script_output_do_not_pass(task):
    """Without the script (or with a fake that prints nothing useful) even a perfect answer stays below 0.67."""
    assert score(task, "", GOOD_ANSWERS[task]) < PASS_SCORE
    assert score(task, "", GITIGNORE_HABIT_ANSWERS[task]) < PASS_SCORE


@pytest.mark.parametrize("task", sorted(TASK_ARGS))
def test_trace_graders_also_hold_for_other_ways_of_running_the_script(task, capsys, monkeypatch):
    """The real script must keep passing when the agent asks for Markdown or runs the paths one at a time."""
    monkeypatch.chdir(FIXTURES / task)
    traces = regex_graders(task, "trace")
    audit.main([*TASK_ARGS[task], "--lang", "en", "--format", "md"])
    captured = capsys.readouterr()
    markdown = captured.out + captured.err
    assert all(rx.search(markdown) for _, rx in traces), markdown
    args = TASK_ARGS[task]
    if "--explain" in args:
        paths = args[2::2]
        split = ""
        for path in paths:
            audit.main([".", "--explain", path, "--lang", "en"])
            captured = capsys.readouterr()
            split += captured.out + captured.err
        assert all(rx.search(split) for _, rx in traces), split


def test_each_mutant_patches_something(capsys, monkeypatch):
    """Guard against a mutant that silently stopped applying: every mutant changes at least one case."""
    real = {task: run_script(task, capsys, monkeypatch) for task in TASK_ARGS}
    for mutant in MUTANTS:
        changed = [t for t in TASK_ARGS if mutated_trace(t, mutant, capsys, monkeypatch) != real[t]]
        assert changed, f"{mutant} changes no case"


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_mutants_that_change_a_case_fail_it(mutant, capsys, monkeypatch):
    """A mutant that changes what the script prints for a case must make that case fail,
    both when the agent copies the wrong output and when it answers correctly by hand."""
    survived = []
    for task in sorted(TASK_ARGS):
        real = run_script(task, capsys, monkeypatch)
        trace = mutated_trace(task, mutant, capsys, monkeypatch)
        if trace == real:
            continue  # equivalent for this fixture: no grader can tell
        hand = score(task, trace, GOOD_ANSWERS[task])
        if hand >= PASS_SCORE:
            survived.append(f"{task} (hand-made answer {hand:.3f})")
        if task in PASTED_TASKS:
            copied = score(task, trace, trace)
            if copied >= PASS_SCORE:
                survived.append(f"{task} (pasted output {copied:.3f})")
    assert not survived, f"{mutant} survives: {survived}"


def test_every_case_is_killed_by_most_mutants(capsys, monkeypatch):
    """Per case: the script's core rules (verdict, last match, anchoring, line numbers) all reach it."""
    core = ("verdict_flip", "line_plus_one", "root_ignore_only")
    for task in sorted(TASK_ARGS):
        real = run_script(task, capsys, monkeypatch)
        killed = [m for m in MUTANTS if score(task, mutated_trace(task, m, capsys, monkeypatch), GOOD_ANSWERS[task]) < PASS_SCORE]
        assert real  # the fixture produced output
        for m in core:
            if task == "task-error-syntax" and m == "verdict_flip":
                continue  # the syntax error stops the script before any path is judged
            assert m in killed, f"{task} is not killed by {m}"
        assert len(killed) >= 3, f"{task}: only {killed}"
