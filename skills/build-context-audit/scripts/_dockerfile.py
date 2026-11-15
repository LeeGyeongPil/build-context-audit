"""Find the local sources of COPY and ADD instructions in a Dockerfile.

Handles line continuations, comments inside continuations, JSON-array form,
flags, and heredocs. Instructions that cannot be judged from the context alone
(``--from`` copies, heredocs) carry a ``skip`` reason instead of sources.
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field

_HEREDOC = re.compile(r"<<(-?)([\"']?)([A-Za-z_][\w-]*)\2")
_REMOTE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://|git@)")
_DIRECTIVE = re.compile(r"^#\s*([A-Za-z][\w-]*)\s*=\s*(\S+)\s*$")


@dataclass
class Instruction:
    line: int  # first physical line of the instruction
    keyword: str  # COPY | ADD
    flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    dest: str = ""
    skip: str | None = None  # "from" | "heredoc" | "unparsable"


@dataclass
class Parsed:
    instructions: list[Instruction] = field(default_factory=list)
    escape_directive_line: int | None = None


def is_remote(source: str) -> bool:
    return bool(_REMOTE.match(source))


def has_variable(source: str) -> bool:
    return "$" in source


def _split_args(rest: str) -> list[str]:
    stripped = rest.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            if isinstance(data, list) and all(isinstance(x, str) for x in data):
                return data
        except ValueError:
            pass
    try:
        return shlex.split(stripped)
    except ValueError:
        return stripped.split()


def parse(text: str) -> Parsed:
    """Parse the COPY and ADD instructions of a Dockerfile."""
    result = Parsed()
    lines = text.splitlines()
    if lines and lines[0].startswith("﻿"):
        lines[0] = lines[0][1:]
    i = 0
    seen_instruction = False
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        number = i + 1
        i += 1
        if not stripped:
            continue
        if stripped.startswith("#"):
            m = _DIRECTIVE.match(stripped)
            if m and not seen_instruction and m.group(1).lower() == "escape":
                result.escape_directive_line = number
            continue
        seen_instruction = True
        logical = stripped
        while logical.endswith("\\"):
            logical = logical[:-1].rstrip()
            # comment and blank lines inside a continuation are dropped, the continuation goes on
            while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("#")):
                i += 1
            if i >= len(lines):
                break
            logical = (logical + " " + lines[i].strip()).strip()
            i += 1
        parts = logical.split(None, 1)
        keyword = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ""
        heredocs = _HEREDOC.findall(rest) if keyword in ("RUN", "COPY", "ADD") else []
        for dash, _quote, name in heredocs:
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body) == name:
                    break
        if keyword not in ("COPY", "ADD"):
            continue
        ins = Instruction(number, keyword)
        if heredocs:
            ins.skip = "heredoc"
            result.instructions.append(ins)
            continue
        args = _split_args(rest)
        while args and args[0].startswith("--"):
            ins.flags.append(args.pop(0))
        if any(f.split("=", 1)[0] == "--from" for f in ins.flags):
            ins.skip = "from"
        elif len(args) < 2:
            ins.skip = "unparsable"
        if len(args) >= 2:
            ins.sources, ins.dest = args[:-1], args[-1]
        result.instructions.append(ins)
    return result
