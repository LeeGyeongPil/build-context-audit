# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-15

### Added

- `audit.py`: computes the files a docker build context sends, with `.dockerignore` semantics matching the Docker CLI
  (root anchoring, parent match, `**`, last matching line wins, `<Dockerfile>.dockerignore` precedence, case-sensitive).
- Per-file verdicts with the deciding ignore-file line, totals, largest folders, `--explain PATH`, `--list`.
- COPY/ADD cross-check: line continuations, JSON form, flags, wildcards, folder sources; `--from`, URL and heredoc sources are skipped.
- Secret-looking file names (no content scan) and hints: `root-anchored`, `unused-rule`, `shadowed-exception`,
  `suffix-match`, `inline-comment` (a `#` after a pattern is not a comment), `bang-class` (`[!x]` is not a negation), `escape-directive`.
- `--suggest` (minimal fix line, re-computed and verified with side effects) and `--compare-ignore` (what-if diff).
- Text, Markdown and JSON output, `--fail-on`, exit codes 0/1/2/3, English and Korean (`--lang`, `BUILD_CONTEXT_AUDIT_LANG`).
- Agent skill (`SKILL.md`, `references/semantics.md`), Claude Code plugin manifests, evaluation set and demo context.
