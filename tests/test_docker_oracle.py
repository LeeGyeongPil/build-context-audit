"""Compare the script with a real ``docker build`` when a Docker daemon is reachable (CI); skipped otherwise.

The oracle Dockerfile copies the whole context into the image and lists it, so the list is exactly what the
builder received after ``.dockerignore`` was applied.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

import audit
from conftest import DEMO

ORACLE = "FROM busybox:1.36\nCOPY . /ctx\nRUN cd /ctx && find . -type f | sort | sed 's/^/CTXFILE /'\n"


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not docker_ready(), reason="no reachable Docker daemon")


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "build.Dockerfile"])
def test_included_files_match_docker(dockerfile, tmp_path, capsys):
    ctx = tmp_path / "context"
    shutil.copytree(DEMO, ctx)
    (ctx / dockerfile).write_text(ORACLE, encoding="utf-8")
    build = subprocess.run(
        ["docker", "build", "--no-cache", "--progress=plain", "-f", str(ctx / dockerfile), str(ctx)],
        capture_output=True, text=True, timeout=600,
    )
    if build.returncode != 0:
        pytest.skip(f"docker build could not run here: {build.stderr[-200:]}")
    from_docker = set(re.findall(r"CTXFILE \./(\S.*)$", build.stdout + build.stderr, re.M))
    code = audit.main([str(ctx), "-f", str(ctx / dockerfile), "--format", "json", "--list", "included"])
    assert code in (0, 1)
    ours = {f["path"] for f in json.loads(capsys.readouterr().out)["files"]}
    assert ours == from_docker


# The evaluation fixtures hold the traps the skill is measured on (inline '#', '[!R]', trailing '/', re-include
# inside an excluded folder, Dockerfile-specific ignore file); the real builder must agree on every one.
@pytest.mark.parametrize(
    ("case", "dockerfile"),
    [
        ("task-context-total", "Dockerfile"),
        ("task-deciding-lines", "Dockerfile"),
        ("task-compare", "Dockerfile"),
        ("task-dockerfile-specific", "docker/api.Dockerfile"),
        ("task-secrets", "Dockerfile"),
    ],
)
def test_evaluation_fixtures_match_docker(case, dockerfile, tmp_path, capsys):
    from conftest import REPO

    ctx = tmp_path / "context"
    shutil.copytree(REPO / "evals" / "fixtures" / case, ctx)
    (ctx / dockerfile).write_text(ORACLE, encoding="utf-8")
    build = subprocess.run(
        ["docker", "build", "--no-cache", "--progress=plain", "-f", str(ctx / dockerfile), str(ctx)],
        capture_output=True, text=True, timeout=600,
    )
    if build.returncode != 0:
        pytest.skip(f"docker build could not run here: {build.stderr[-200:]}")
    from_docker = set(re.findall(r"CTXFILE \./(\S.*)$", build.stdout + build.stderr, re.M))
    code = audit.main([str(ctx), "-f", str(ctx / dockerfile), "--format", "json", "--list", "included"])
    assert code in (0, 1)
    ours = {f["path"] for f in json.loads(capsys.readouterr().out)["files"]}
    assert ours == from_docker
