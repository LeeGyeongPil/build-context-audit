"""Walk a build context the way the builder sees it: symbolic links are entries, never followed."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    path: str  # slash-separated, relative to the context root
    size: int  # bytes (lstat: a symbolic link counts as the link itself)


@dataclass
class Walked:
    files: list[Entry] = field(default_factory=list)
    dirs: set[str] = field(default_factory=set)
    unreadable: list[str] = field(default_factory=list)


def walk(root: Path) -> Walked:
    """List every file below ``root`` in sorted order with its size, in a single pass."""
    result = Walked()
    stack: list[tuple[str, str]] = [("", str(root))]
    while stack:
        rel, real = stack.pop()
        try:
            with os.scandir(real) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            result.unreadable.append(rel or ".")
            continue
        subdirs: list[tuple[str, str]] = []
        for entry in entries:
            name = f"{rel}/{entry.name}" if rel else entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    result.dirs.add(name)
                    subdirs.append((name, entry.path))
                elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    result.files.append(Entry(name, entry.stat(follow_symlinks=False).st_size))
            except OSError:
                result.unreadable.append(name)
        stack.extend(reversed(subdirs))
    result.files.sort(key=lambda e: e.path)
    return result
