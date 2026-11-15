"""AC-2, AC-3, AC-4: the exact verdicts of the demo context (demo/context)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import DEMO, PROPOSED, REPO, SOURCE_DEMO

DOCKERFILE = str(DEMO / "build.Dockerfile")


def demo_json(cli, *extra: str):
    result = cli(str(DEMO), "--format", "json", *extra)
    return result, result.json()


def test_demo_files_present():
    """The secret-looking demo files are placeholders and must not be hidden by the repository's .gitignore."""
    needed = [
        ".dockerignore", ".env", "Dockerfile", "build.Dockerfile", "build.Dockerfile.dockerignore",
        "certs/server.key", "deploy/id_rsa", "node_modules/left-pad/index.js",
        "web/node_modules/react/index.js", "README-secret.md", "app/config.yaml",
    ]
    for rel in needed:
        assert (DEMO / rel).is_file(), rel
    assert PROPOSED.is_file()
    assert (DEMO / ".env").read_text() == "APP_MODE=demo\n"
    # the work tree must not contain a file named .env; demo/setup_demo.py creates it on demand
    assert not (SOURCE_DEMO / ".env").exists()
    if shutil.which("git") and (REPO / ".git").exists():
        for rel in needed:
            if rel == ".env":
                continue
            ignored = subprocess.run(
                ["git", "-C", str(REPO), "check-ignore", "-q", f"demo/context/{rel}"], capture_output=True
            ).returncode
            assert ignored == 1, f"{rel} is ignored by git"


def test_demo_exit_code_is_one(cli):
    result, _ = demo_json(cli)
    assert result.code == 1


def test_demo_ignore_file_and_totals(cli):
    _, rep = demo_json(cli)
    assert rep["ignore_file"] == ".dockerignore"
    assert rep["ignore_file_reason"] == "root"
    sizes = {p.relative_to(DEMO).as_posix(): p.stat().st_size for p in DEMO.rglob("*") if p.is_file()}
    sent = {
        p: s for p, s in sizes.items()
        if p not in {"CHANGELOG.md", "README-secret.md", "app/config.yaml", "node_modules/left-pad/index.js"}
    }
    assert rep["totals"] == {
        "included_files": len(sent),
        "included_bytes": sum(sent.values()),
        "excluded_files": 4,
        "excluded_bytes": sum(sizes.values()) - sum(sent.values()),
    }


def test_demo_largest_folder_is_web_with_nested_node_modules(cli):
    _, rep = demo_json(cli, "--list", "included")
    assert rep["top_dirs"][0] == {"path": "web", "bytes": 9000, "files": 1}
    files = {f["path"]: f for f in rep["files"]}
    assert files["web/node_modules/react/index.js"]["included"] is True
    assert files["web/node_modules/react/index.js"]["rule"] is None
    assert "node_modules/left-pad/index.js" not in files


def test_demo_root_anchored_markdown_rule(cli):
    _, rep = demo_json(cli, "--list", "all")
    files = {f["path"]: f for f in rep["files"]}
    assert files["docs/guide.md"]["included"] is True
    assert files["README-secret.md"]["included"] is False
    assert files["README-secret.md"]["rule"] == {"file": ".dockerignore", "line": 4, "pattern": "README-secret.md"}
    assert files["README.md"]["rule"]["line"] == 3
    assert files["CHANGELOG.md"]["rule"]["line"] == 2


def test_demo_copy_checks(cli):
    _, rep = demo_json(cli)
    by_line = {c["dockerfile_line"]: c for c in rep["copy_checks"]}
    assert by_line[2]["status"] == "ok"
    assert by_line[3]["source"] == "app/config.yaml"
    assert by_line[3]["status"] == "excluded"
    assert by_line[3]["rule"] == {"file": ".dockerignore", "line": 7, "pattern": "app/*.yaml"}
    assert by_line[5]["source"] == "README-secret.md"
    assert by_line[5]["status"] == "excluded"
    assert by_line[5]["rule"]["line"] == 4
    assert by_line[6]["status"] == "skipped" and by_line[6]["note"] == "from"
    assert by_line[7]["status"] == "skipped" and by_line[7]["note"] == "remote"
    assert by_line[8]["source"] == "docs/*.md" and by_line[8]["status"] == "ok"


def test_demo_secrets(cli):
    _, rep = demo_json(cli)
    assert [s["path"] for s in rep["secrets"]] == [".env", "certs/server.key", "deploy/id_rsa"]
    assert [s["kind"] for s in rep["secrets"]] == ["env", "private-key", "ssh-key"]


def test_demo_json_has_the_documented_keys(cli):
    _, rep = demo_json(cli)
    for key in (
        "ignore_file", "ignore_file_reason", "totals", "top_dirs", "copy_checks", "secrets",
        "hints", "explain", "suggestions", "compare",
    ):
        assert key in rep
    assert "files" not in rep


def test_dockerfile_specific_ignore_file_wins(cli):
    result, rep = demo_json(cli, "-f", DOCKERFILE, "--list", "included")
    assert rep["ignore_file"] == "build.Dockerfile.dockerignore"
    assert rep["ignore_file_reason"] == "dockerfile-specific"
    assert sorted(f["path"] for f in rep["files"]) == ["app/config.yaml", "app/main.py", "requirements.txt"]
    docs = next(c for c in rep["copy_checks"] if c["source"] == "docs/*.md")
    assert docs["status"] == "excluded"
    assert docs["rule"] == {"file": "build.Dockerfile.dockerignore", "line": 1, "pattern": "**"}
    assert rep["secrets"] == []
    assert result.code == 1


def test_dockerfile_specific_first_line_of_text_report(cli):
    result = cli(str(DEMO), "-f", DOCKERFILE)
    assert result.out.splitlines()[0] == "ignore file: build.Dockerfile.dockerignore (root .dockerignore is NOT used)"
    assert "build.Dockerfile:4 COPY docs/*.md  EXCLUDED" in result.out
    assert "decided by build.Dockerfile.dockerignore:1 '**'" in result.out


def test_explain_shows_all_matching_lines_in_order(cli):
    _, rep = demo_json(cli, "--explain", "README-secret.md")
    ex = rep["explain"][0]
    assert ex["included"] is False
    assert [(h["line"], h["effect"], h["deciding"]) for h in ex["history"]] == [
        (2, "exclude", False),
        (3, "include", False),
        (4, "exclude", True),
    ]
    assert ex["rule"]["line"] == 4


def test_explain_text_marks_the_deciding_line(cli):
    result = cli(str(DEMO), "--explain", "README-secret.md", "--explain", "app/config.yaml")
    assert "README-secret.md: EXCLUDED — decided by .dockerignore:4 'README-secret.md'" in result.out
    assert "app/config.yaml: EXCLUDED — decided by .dockerignore:7 'app/*.yaml'" in result.out
    marked = [ln for ln in result.out.splitlines() if "<== decides" in ln]
    assert len(marked) == 2 and "README-secret.md' matches -> excludes" in marked[0]


def test_explain_nested_path_points_at_the_anchoring_problem(cli):
    _, rep = demo_json(cli, "--explain", "web/node_modules/react/index.js")
    ex = rep["explain"][0]
    assert ex["included"] is True and ex["history"] == []
    assert "**/node_modules" in ex["notes"][0]


def test_explain_accepts_absolute_and_dotted_paths(cli):
    for raw in (str(DEMO / "app" / "config.yaml"), "./app/config.yaml"):
        _, rep = demo_json(cli, "--explain", raw)
        assert rep["explain"][0]["path"] == "app/config.yaml"
        assert rep["explain"][0]["rule"]["line"] == 7


def test_explain_unknown_path_is_judged_by_the_lines_only(cli):
    result = cli(str(DEMO), "--explain", "nope/x.md")
    assert "no such file or folder in the context" in result.out
    _, rep = demo_json(cli, "--explain", "nope/x.md")
    assert rep["explain"][0]["kind"] == "unknown"


# A line that matches only through a folder where the builder skipped it never reaches the file. --explain must say
# so, not "no effect (verdict already the same)" (review Q-1), in both languages.
FOLDER_EXCEPTION = {
    "Dockerfile": "FROM scratch\n", ".dockerignore": "**/*.key\n!certs\n", "certs/tls.key": "k", "certs/server.pem": "p",
}
FOLDER_UNDO = {
    "Dockerfile": "FROM scratch\n", ".dockerignore": "docs\n!docs/keep.md\ndocs\n", "docs/keep.md": "x", "docs/other.md": "y",
}


def test_explain_folder_exception_that_does_not_reach_the_file(cli, make_ctx):
    ctx = make_ctx(FOLDER_EXCEPTION)
    rep = cli(str(ctx), "--format", "json", "--explain", "certs/tls.key", "--explain", "certs/server.pem").json()
    key, pem = rep["explain"]
    assert key["included"] is False and key["rule"]["line"] == 1  # verdict and deciding line unchanged
    assert [(h["line"], h["effect"], h["deciding"], h["folder"], h["fix"]) for h in key["history"]] == [
        (1, "exclude", True, None, None),
        (2, "folder-skip", False, "certs", "!certs/tls.key"),
    ]
    # server.pem is already sent: '!certs' would change nothing there, so "already the same" is the true reason
    assert [(h["line"], h["effect"]) for h in pem["history"]] == [(2, "no-effect")]

    out = cli(str(ctx), "--explain", "certs/tls.key", "--lang", "en").out
    row = next(ln for ln in out.splitlines() if "'!certs' matches ->" in ln)
    assert "verdict already the same" not in row
    assert "only through folder 'certs'" in row and "'!certs/tls.key'" in row

    out = cli(str(ctx), "--explain", "certs/tls.key", "--lang", "ko").out
    row = next(ln for ln in out.splitlines() if "'!certs' 일치 ->" in ln)
    assert "이미 같은 판정" not in row
    assert "폴더 'certs' 를 통해서만" in row and "'!certs/tls.key'" in row


def test_explain_later_folder_line_that_does_not_undo_a_file_exception(cli, make_ctx):
    ctx = make_ctx(FOLDER_UNDO)
    rep = cli(str(ctx), "--format", "json", "--explain", "docs/keep.md", "--explain", "docs/other.md").json()
    keep, other = rep["explain"]
    assert keep["included"] is True and keep["rule"]["line"] == 2
    assert [(h["line"], h["effect"], h["deciding"]) for h in keep["history"]] == [
        (1, "exclude", False),
        (2, "include", True),
        (3, "folder-skip", False),
    ]
    assert keep["history"][2]["folder"] == "docs" and keep["history"][2]["fix"] == "docs/keep.md"
    assert [(h["line"], h["effect"]) for h in other["history"]] == [(1, "exclude"), (3, "no-effect")]

    out = cli(str(ctx), "--explain", "docs/keep.md", "--lang", "ko").out
    row = next(ln for ln in out.splitlines() if ":3 'docs' 일치 ->" in ln)
    assert "이미 같은 판정" not in row and "폴더 'docs' 를 통해서만" in row and "'docs/keep.md'" in row
    out = cli(str(ctx), "--explain", "docs/keep.md", "--lang", "en").out
    row = next(ln for ln in out.splitlines() if ":3 'docs' matches ->" in ln)
    assert "verdict already the same" not in row and "only through folder 'docs'" in row


@pytest.mark.parametrize(
    ("files", "line", "folder", "example"),
    [(FOLDER_EXCEPTION, 2, "certs", "certs/tls.key"), (FOLDER_UNDO, 3, "docs", "docs/keep.md")],
)
def test_unused_rule_hint_names_the_folder_skip(cli, make_ctx, files, line, folder, example):
    # the hint for the same line gives the same reason instead of "decided by another line"
    ctx = make_ctx(files)
    for lang, text, wrong in (
        ("en", f"only through folder '{folder}'", "decided by another line"),
        ("ko", f"폴더 '{folder}' 를 통해서만", "다른 줄이 결정"),
    ):
        rep = cli(str(ctx), "--format", "json", "--lang", lang).json()
        hint = next(h for h in rep["hints"] if h["line"] == line)
        assert hint["code"] == "unused-rule"
        assert text in hint["message"] and f"--explain {example}" in hint["message"] and wrong not in hint["message"]
        assert "'!certs/tls.key'" not in hint["message"]  # the hint never proposes re-including a key file


def test_suggest_for_the_folder_exception_case_is_unchanged(cli, make_ctx):
    ctx = make_ctx({**FOLDER_EXCEPTION, "Dockerfile": "FROM scratch\nCOPY certs/tls.key /k\n"})
    rep = cli(str(ctx), "--format", "json", "--suggest").json()
    assert [(s["add_line"], s["verified"]) for s in rep["suggestions"]][:1] == [("!certs/tls.key", True)]


def hints_by_code(rep):
    out = {}
    for h in rep["hints"]:
        out.setdefault(h["code"], []).append(h)
    return out


def test_hints_root_anchored_and_unused_rule(cli):
    _, rep = demo_json(cli)
    codes = hints_by_code(rep)
    node = next(h for h in codes["root-anchored"] if h["line"] == 5)
    assert node["pattern"] == "node_modules"
    assert "**/node_modules" in node["message"] and "web/node_modules" in node["message"]
    unused = codes["unused-rule"]
    assert [h["line"] for h in unused] == [6]
    assert unused[0]["pattern"] == ".git"


def test_unused_rule_disappears_when_a_git_folder_exists(cli, demo_copy):
    (demo_copy / ".git").mkdir()
    (demo_copy / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    result = cli(str(demo_copy), "--format", "json")
    rep = result.json()
    assert "unused-rule" not in hints_by_code(rep)
    assert all(s["path"] != ".git/" for s in rep["secrets"]) is True  # .git is excluded by line 6


def test_git_folder_is_a_secret_when_the_ignore_file_forgets_it(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".git/HEAD": "ref\n", "a.txt": "x"})
    rep = cli(str(ctx), "--format", "json").json()
    assert rep["secrets"] == [{"path": ".git/", "kind": "git-dir", "rule_hint": ".git"}]


def test_suffix_match_hint(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".dockerignore": "**file\n", "profile": "x", "file": "y", "keep": "z"})
    rep = cli(str(ctx), "--format", "json").json()
    hint = hints_by_code(rep)["suffix-match"][0]
    # `Dockerfile` itself ends in "file", so the first example is the Dockerfile: the quirk bites immediately
    assert hint["line"] == 1 and "ending in 'file'" in hint["message"] and "'Dockerfile'" in hint["message"]


def test_shadowed_exception_hint(cli, make_ctx):
    ctx = make_ctx(
        {"Dockerfile": "FROM scratch\n", ".dockerignore": "*.md\n!README.md\nREADME.md\n", "README.md": "x", "a.txt": "y"}
    )
    rep = cli(str(ctx), "--format", "json").json()
    shadowed = hints_by_code(rep)["shadowed-exception"]
    assert [h["line"] for h in shadowed] == [2]


def test_inline_comment_hint_and_the_line_has_no_effect(cli, make_ctx):
    # Docker has no inline comments: the whole line is one pattern that matches nothing
    ctx = make_ctx(
        {"Dockerfile": "FROM scratch\n", ".dockerignore": "# real comment\n*.bak  # editor backups\n", "a.bak": "x"}
    )
    rep = cli(str(ctx), "--format", "json", "--list", "all").json()
    codes = hints_by_code(rep)
    hint = codes["inline-comment"][0]
    assert hint["line"] == 2 and hint["pattern"] == "*.bak  # editor backups"
    assert "'*.bak' has no effect" in hint["message"]
    assert "unused-rule" not in codes  # explained once, by the inline-comment hint
    assert "a.bak" in [f["path"] for f in rep["files"] if f["included"]]


def test_bang_class_hint_and_its_real_meaning(cli, make_ctx):
    # '[!R]' is the set {'!', 'R'} in Go: README.md is excluded, guide.md is sent
    ctx = make_ctx(
        {"Dockerfile": "FROM scratch\n", ".dockerignore": "[!R]*.md\n\\[!x]\n", "README.md": "x", "guide.md": "y"}
    )
    rep = cli(str(ctx), "--format", "json", "--list", "all").json()
    hints = hints_by_code(rep)["bang-class"]
    assert [h["line"] for h in hints] == [1]  # an escaped '\[!' is a literal bracket, no hint
    assert "'[^R]*.md'" in hints[0]["message"]
    included = {f["path"] for f in rep["files"] if f["included"]}
    assert "guide.md" in included and "README.md" not in included


def test_escape_directive_hint(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "# escape=`\nFROM scratch\nCOPY a.txt /a\n", "a.txt": "x"})
    rep = cli(str(ctx), "--format", "json").json()
    assert hints_by_code(rep)["escape-directive"][0]["line"] == 1


def test_list_is_capped_in_text_but_complete_in_json(cli):
    text = cli(str(DEMO), "--list", "all", "--max-list", "2").out
    assert "showing 2 of 16" in text
    assert len(cli(str(DEMO), "--list", "all", "--format", "json", "--max-list", "2").json()["files"]) == 16


def test_top_option_limits_folders(cli):
    assert len(demo_json(cli, "--top", "2")[1]["top_dirs"]) == 2
    assert demo_json(cli, "--top", "0")[1]["top_dirs"] == []


def test_markdown_report_has_sections(cli):
    out = cli(str(DEMO), "--format", "md").out
    assert out.startswith("# build-context-audit report")
    assert "## COPY/ADD check (Dockerfile)" in out and "## Hints" in out


def test_out_writes_a_file_and_nothing_to_stdout(cli, tmp_path):
    target = tmp_path / "report.json"
    result = cli(str(DEMO), "--format", "json", "--out", str(target))
    assert result.out == "" and result.code == 1
    assert '"copy_checks"' in target.read_text(encoding="utf-8")


def test_ignore_file_option_for_other_container_tools(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY a.txt /a\n", "a.txt": "x", ".containerignore": "a.txt\n"})
    rep = cli(str(ctx), "--ignore-file", str(ctx / ".containerignore"), "--format", "json").json()
    assert rep["ignore_file"] == ".containerignore" and rep["ignore_file_reason"] == "explicit"
    assert rep["copy_checks"][0]["status"] == "excluded"


def test_symbolic_links_are_entries_not_followed(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", "real/a.txt": "x" * 100})
    (ctx / "link").symlink_to(ctx / "real")
    rep = cli(str(ctx), "--format", "json", "--list", "all").json()
    paths = [f["path"] for f in rep["files"]]
    assert "link" in paths and "link/a.txt" not in paths


@pytest.mark.parametrize("flag", ["--max-list", "--top"])
def test_negative_numbers_are_a_usage_error(cli, flag):
    result = cli(str(DEMO), flag, "-1")
    assert result.code == 2 and "must be 0 or more" in result.err


def test_setup_demo_refuses_to_delete_a_foreign_folder(tmp_path):
    import setup_demo

    mine = tmp_path / "work"
    mine.mkdir()
    (mine / "keep.txt").write_text("important", encoding="utf-8")
    assert setup_demo.main([str(mine)]) == 2
    assert (mine / "keep.txt").read_text(encoding="utf-8") == "important"


def test_setup_demo_replaces_empty_and_its_own_copy(tmp_path):
    import setup_demo

    empty = tmp_path / "empty"
    empty.mkdir()
    assert setup_demo.main([str(empty)]) == 0
    assert setup_demo.main([str(empty)]) == 0  # an earlier demo copy (demo files only) may be rebuilt
    assert (empty / ".env").is_file()
