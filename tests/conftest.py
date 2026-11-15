"""Shared helpers: run the CLI in-process, build throwaway contexts, keep the locale out of the tests."""
from __future__ import annotations

import atexit
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

import audit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "demo"))
import setup_demo  # noqa: E402

# The repository tracks no file named .env, so tests use a generated copy outside the work tree.
_DEMO_ROOT = Path(tempfile.mkdtemp(prefix="bca-demo-"))
atexit.register(shutil.rmtree, _DEMO_ROOT, ignore_errors=True)
DEMO = setup_demo.build(_DEMO_ROOT / "context")
SOURCE_DEMO = REPO / "demo" / "context"
PROPOSED = REPO / "demo" / "proposed.dockerignore"


@pytest.fixture(autouse=True)
def _english_by_default(monkeypatch):
    """Tests must not depend on the developer's locale."""
    for name in ("BUILD_CONTEXT_AUDIT_LANG", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "C")


class Result:
    def __init__(self, code: int, out: str, err: str):
        self.code, self.out, self.err = code, out, err

    def json(self) -> dict:
        return json.loads(self.out)


@pytest.fixture
def cli(capsys):
    """cli('demo/context', '--format', 'json') runs audit.main and returns Result(code, out, err)."""

    def run(*argv: str) -> Result:
        code = audit.main(list(argv))
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return run


def write_tree(root: Path, files: dict[str, str]) -> Path:
    """Create ``files`` (relative path -> text) below ``root`` and return ``root``."""
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def make_ctx(tmp_path):
    """make_ctx({'Dockerfile': ..., '.dockerignore': ...}) -> a private context folder."""

    def build(files: dict[str, str]) -> Path:
        return write_tree(tmp_path / "ctx", files)

    return build


@pytest.fixture
def demo_copy(tmp_path) -> Path:
    """A private copy of demo/context that a test may change."""
    dest = tmp_path / "context"
    shutil.copytree(DEMO, dest)
    return dest
