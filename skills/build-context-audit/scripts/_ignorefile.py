"""Pick which ignore file the builder reads, and read it.

Docker prefers ``<Dockerfile name>.dockerignore`` next to the Dockerfile over the
context's ``.dockerignore``; the two are never merged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from _matcher import IgnoreLine, read_ignore_lines

REASONS = ("dockerfile-specific", "root", "explicit", "none")


@dataclass(frozen=True)
class IgnoreChoice:
    path: Path | None
    display: str | None  # relative to the context when inside it
    reason: str  # one of REASONS
    root_exists: bool  # a root .dockerignore exists although it is not used


def display_path(path: Path, context: Path) -> str:
    """Show ``path`` relative to the context when it lives inside it, else as given."""
    try:
        return path.resolve().relative_to(context.resolve()).as_posix()
    except ValueError:
        return str(path)


def choose(context: Path, dockerfile: Path, explicit: str | None) -> IgnoreChoice:
    """Dockerfile-specific file > root ``.dockerignore``; ``--ignore-file`` overrides both."""
    root = context / ".dockerignore"
    root_exists = root.is_file()
    if explicit:
        path = Path(explicit)
        return IgnoreChoice(path, display_path(path, context), "explicit", root_exists)
    specific = dockerfile.parent / (dockerfile.name + ".dockerignore")
    if specific.is_file():
        return IgnoreChoice(specific, display_path(specific, context), "dockerfile-specific", root_exists)
    if root_exists:
        return IgnoreChoice(root, ".dockerignore", "root", True)
    return IgnoreChoice(None, None, "none", False)


def read_lines(path: Path) -> list[IgnoreLine]:
    """Read and normalise an ignore file (raises OSError / UnicodeDecodeError on failure)."""
    return read_ignore_lines(path.read_text(encoding="utf-8"))
