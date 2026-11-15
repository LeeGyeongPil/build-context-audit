---
name: build-context-audit
description: Computes with a bundled script exactly which files a docker build context sends once .dockerignore is applied (root-anchored matching, last matching line wins, per-Dockerfile ignore file), names the ignore-file line that decided each path, cross-checks COPY and ADD sources, flags secret-looking files and oversized folders, and re-verifies a proposed fix line or replacement ignore file before anything is edited. Use when a docker build fails with a COPY error saying the file was not found in the build context or excluded by .dockerignore, when the build context is huge or node_modules still gets uploaded, when asked which .dockerignore line excludes a file, whether .env or key files end up in the image, which ignore file docker build -f reads, or to write, tighten or check a .dockerignore before building (also asked in Korean about 도커 .dockerignore 때문에 빠지는 파일). Not for image layers or size, multi-stage builds, .gitignore, .npmignore, docker-compose settings or build secret mounts.
license: MIT
compatibility: Python 3.10+ (standard library only). No network access, no Docker daemon needed.
---

# Audit a docker build context before building

Your next step is one command in the user's project folder: the script reads the Dockerfile and the ignore file, walks
the folder and prints what the builder will really receive. Do not work the rules out in your head and do not run
`docker build` to find out. People and models misjudge `.dockerignore` by hand, because it is not `.gitignore`: every
pattern is anchored to the context root (`*.md` does not hit `docs/a.md`, `node_modules` does not hit
`web/node_modules`), the last matching line wins, but folder by folder (after `**/*.key`, `!certs` does not bring
back `certs/tls.key`),
`<Dockerfile name>.dockerignore` replaces `.dockerignore` completely when it exists, `#` is a comment only in column 1
(`*.bak  # backups` is one pattern that matches nothing), `[!R]` is the set `!`,`R` and not a negation (`[!R]*.md`
removes `README.md`), and a trailing `/` also matches a file (`release/` removes the script `release`).

`<skill-dir>` below is the folder that holds this SKILL.md; the bundled script is `scripts/audit.py` inside it. Call it by that full path and stay in the user's folder.

```
python3 <skill-dir>/scripts/audit.py CONTEXT [-f DOCKERFILE] --lang en
```

- Use `--lang en` when the user writes English and `--lang ko` for Korean; without it the machine locale picks the
  language. Numbers, paths and `file:line 'pattern'` strings are the same in both.

- `CONTEXT` is the folder given to `docker build` (usually `.`). `-f` is the same value the user passes to `docker build -f`
  (default `CONTEXT/Dockerfile`). The script chooses the ignore file itself and prints its name on the first line;
  `--ignore-file FILE` forces another one, for example `.containerignore`.
- Which line excludes or includes a path: add `--explain PATH`, once per path in the same run. It lists every matching
  line in order and marks the one that decides. Use it for every "why" or "which line" question instead of reasoning
  from memory: an exception inside an excluded folder does work in Docker, and a later line can undo it, but a line
  that hits a file only through its folder applies only if it could change that folder's verdict at that point
  (`!certs` after `**/*.key` keeps `certs/tls.key` out; `docs`, `!docs/keep.md`, `docs` still sends `docs/keep.md`).
  `--explain` marks such a line `does not reach this path`.
- Fixing a failed COPY or a secret: add `--suggest`. It proposes one line to append, applies it to a copy, re-computes the
  whole audit and prints `verified` plus the files that come in or drop out. Offer only lines that came out verified.
- Rewriting or tightening the ignore file: write the candidate to a separate file, run `--compare-ignore CANDIDATE` and read the
  removed and added files, the byte change, the COPY status changes and the secret count before touching `.dockerignore`.
- More detail: `--list excluded|included|all` (capped by `--max-list`, default 50), `--top N` folders, `--format json` for
  data, `--lang ko` for Korean. Output goes to stdout; `--out FILE` writes a file instead.
- The script never edits anything and never reads file contents (secrets are found by name only). When the fix is accepted,
  make the edit yourself and run the script once more to confirm.
- Why a line behaves as it does: read [references/semantics.md](references/semantics.md) only when you need to explain a rule.

## Reading the output

- First line: the ignore file in use. `(root .dockerignore is NOT used)` means a Dockerfile-specific file replaced it.
- `Sent to the builder` and `Largest folders sent`: total files and bytes, biggest first-level folders.
- `COPY/ADD check`: `ok`, `EXCLUDED` (with the deciding `file:line 'pattern'`), `MISSING` (not in the context at all, check the
  path and its letter case), `skipped` (`--from`, URL or heredoc, not judged) or `unchecked` (path has a variable).
- `Secrets`: secret-looking names that are sent, with the line that would remove each one.
- `Hints`: `root-anchored` (use `**/name`), `unused-rule`, `shadowed-exception`, `suffix-match`, `inline-comment`
  (a `#` after a pattern makes the whole line a no-op), `bang-class` (`[!x]` is not a negation, use `[^x]`),
  `escape-directive`.
- Exit code: 0 nothing found, 1 a COPY/ADD failure or a secret-looking file (`--fail-on warning` adds hints), 2 an input
  problem, 3 an ignore-file syntax error.

## Report back

- Run the script first, then answer from its printed lines. Copy the exact numbers (`N B`, file counts), paths and
  `file:line 'pattern'` strings into your answer verbatim; do not round, convert units or recompute them. State the
  ignore file name from the first line, the sent total from `Sent to the builder`, and name the deciding line.
- Trust the script over your own reading of the ignore file. When a value surprises you, that is one of the traps
  above: explain it with the printed hint or `--explain`, never "correct" the number or the verdict.
- If the user asks for a reply format, fill it with the printed values: `file:N` means `line N`, keep `INCLUDED` or
  `EXCLUDED` as printed, and write `line none` when the script says no line matches.
- For a what-if comparison give the `sent total: A B -> B B` line, the removed and added paths and each `COPY ... -> ...` change.
- For a fix give the verified line exactly as printed with its `side effects`; for a hint give the `**/` pattern it proposes.
- For a COPY failure give the excluded source, the deciding line and the verified fix line with its side effects.
- For size questions give both numbers of `Sent to the builder: N files, M B` and the biggest folders with their bytes,
  and say which hint (`root-anchored`, `inline-comment`, `bang-class`) is the reason.
- For secrets list exactly the paths printed under `Secrets` (no more, no fewer) and the lines to add. Say that the
  check is by file name, not by content.
- Exit code 2 or 3: show the error line as printed, it says how to fix the input, and stop there.
