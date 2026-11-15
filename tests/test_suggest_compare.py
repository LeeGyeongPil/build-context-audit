"""AC-5: verified fix lines and the what-if comparison of a proposed ignore file."""
from __future__ import annotations

from conftest import DEMO, PROPOSED


def test_suggest_for_excluded_copy_is_minimal_and_verified(cli):
    rep = cli(str(DEMO), "--suggest", "--format", "json").json()
    copy = next(s for s in rep["suggestions"] if s["target"] == "COPY app/config.yaml")
    assert copy["add_line"] == "!app/config.yaml"
    assert copy["verified"] is True
    assert copy["dockerfile_line"] == 3
    assert copy["append_to"] == ".dockerignore"
    assert copy["side_effects"] == {"added": ["app/config.yaml"], "removed": []}


def test_suggest_covers_every_failure_and_every_secret_line(cli):
    rep = cli(str(DEMO), "--suggest", "--format", "json").json()
    lines = [s["add_line"] for s in rep["suggestions"]]
    assert lines == ["!app/config.yaml", "!README-secret.md", ".env", "**/*.key", "**/id_rsa"]
    assert all(s["verified"] for s in rep["suggestions"])
    secret = next(s for s in rep["suggestions"] if s["add_line"] == "**/*.key")
    assert secret["side_effects"] == {"added": [], "removed": ["certs/server.key"]}


def test_suggest_text_reports_side_effects(cli):
    out = cli(str(DEMO), "--suggest").out
    assert "Suggested fixes (append to .dockerignore, nothing is written):" in out
    assert "!app/config.yaml   for COPY app/config.yaml" in out
    assert "verified: COPY app/config.yaml is fine after this line; side effects: +1 file, -0 files" in out


def test_suggest_does_not_touch_the_ignore_file(cli, demo_copy):
    before = (demo_copy / ".dockerignore").read_bytes()
    cli(str(demo_copy), "--suggest")
    assert (demo_copy / ".dockerignore").read_bytes() == before


def test_suggest_wildcard_and_directory_sources(cli, make_ctx):
    ctx = make_ctx(
        {"Dockerfile": "COPY docs/*.md /d/\nCOPY app/ /a/\n", ".dockerignore": "docs\napp\n", "docs/a.md": "x", "app/m.py": "y"}
    )
    rep = cli(str(ctx), "--suggest", "--format", "json").json()
    by_target = {s["target"]: s for s in rep["suggestions"]}
    assert by_target["COPY docs/*.md"]["add_line"] == "!docs/*.md" and by_target["COPY docs/*.md"]["verified"]
    assert by_target["COPY app/"]["add_line"] == "!app" and by_target["COPY app/"]["verified"]


def test_suggest_with_nothing_to_fix(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY a.txt /a\n", "a.txt": "x"})
    result = cli(str(ctx), "--suggest")
    assert result.code == 0 and "Nothing to fix" in result.out


def test_suggest_without_an_ignore_file_proposes_the_root_file(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "COPY a.txt /a\n", "key.pem": "x", "a.txt": "x"})
    rep = cli(str(ctx), "--suggest", "--format", "json").json()
    assert rep["suggestions"][0]["append_to"] == ".dockerignore"
    assert rep["suggestions"][0]["add_line"] == "*.pem"


def test_suggest_appends_to_the_dockerfile_specific_file(cli):
    rep = cli(str(DEMO), "-f", str(DEMO / "build.Dockerfile"), "--suggest", "--format", "json").json()
    docs = next(s for s in rep["suggestions"] if s["target"] == "COPY docs/*.md")
    assert docs["append_to"] == "build.Dockerfile.dockerignore"
    assert docs["add_line"] == "!docs/*.md" and docs["verified"] is True
    assert docs["side_effects"]["added"] == ["docs/guide.md"]


def test_compare_with_the_proposed_ignore_file(cli):
    rep = cli(str(DEMO), "--compare-ignore", str(PROPOSED), "--format", "json").json()
    cmp_ = rep["compare"]
    removed = ["web/node_modules/react/index.js", ".env", "certs/server.key", "deploy/id_rsa"]
    assert sorted(cmp_["removed"]) == sorted(removed)
    assert cmp_["added"] == ["app/config.yaml"]
    expected = (DEMO / "app" / "config.yaml").stat().st_size - sum((DEMO / p).stat().st_size for p in removed)
    assert cmp_["bytes_delta"] == expected and expected < 0
    assert (cmp_["secrets_before"], cmp_["secrets_after"]) == (3, 0)
    assert cmp_["copy_changes"] == [
        {
            "dockerfile_line": 3, "instruction": "COPY", "source": "app/config.yaml",
            "before": "excluded", "after": "ok", "rule": None,
        }
    ]
    assert cmp_["file"] == "demo/proposed.dockerignore" or cmp_["file"].endswith("proposed.dockerignore")


def test_compare_leaves_the_base_report_unchanged(cli):
    base = cli(str(DEMO), "--format", "json").json()
    with_cmp = cli(str(DEMO), "--format", "json", "--compare-ignore", str(PROPOSED)).json()
    for key in ("totals", "copy_checks", "secrets"):
        assert base[key] == with_cmp[key]
    assert base["compare"] is None


def test_compare_text(cli):
    out = cli(str(DEMO), "--compare-ignore", str(PROPOSED)).out
    assert "removed 4 files, added 1 file, bytes -9039" in out
    assert "secrets 3 -> 0" in out
    assert "Dockerfile:3 COPY app/config.yaml: EXCLUDED -> ok" in out


def test_compare_with_an_identical_file_changes_nothing(cli):
    rep = cli(str(DEMO), "--compare-ignore", str(DEMO / ".dockerignore"), "--format", "json").json()
    cmp_ = rep["compare"]
    assert cmp_["added"] == [] and cmp_["removed"] == [] and cmp_["bytes_delta"] == 0 and cmp_["copy_changes"] == []


def test_compare_syntax_error_in_the_proposal_is_exit_3(cli, tmp_path):
    bad = tmp_path / "bad.dockerignore"
    bad.write_text("*.md\n[]a]\n")
    result = cli(str(DEMO), "--compare-ignore", str(bad))
    assert result.code == 3 and "bad.dockerignore:2: invalid pattern '[]a]'" in result.err
