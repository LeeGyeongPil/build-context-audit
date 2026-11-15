# How the Docker CLI reads an ignore file

Reference for explaining a verdict. The script implements exactly these rules.

## Reading a line

- Only a `#` in column 1 starts a comment. An indented `# note` is a pattern, and there are no inline comments:
  `*.bak  # backups` is the single pattern `*.bak  # backups`, which matches nothing.
- Spaces around a line are trimmed; blank lines are skipped; a UTF-8 BOM on the first line is removed.
- A leading `!` marks an exception (re-include). A lone `!` is an error.
- Paths are cleaned (`./a//b/` becomes `a/b`) and a leading `/` is dropped, so a trailing `/` does not mean "folders
  only": `release/` also removes a file named `release`.

## Matching

- Patterns are anchored to the context root: `*.md` matches `a.md` but not `docs/a.md`; use `**/*.md`.
- `*` and `?` never cross `/`. `**` matches any number of directories (also none): `a/**/b` matches `a/b`.
- `dir/**` matches everything below `dir` but not `dir` itself.
- A pattern matches a path when it matches the path itself or any parent directory, so `docs` removes `docs/a/b.md`.
- `**` glued to text (`**file`) is a suffix match: it also matches `profile`. Write `**/file` for whole names.
- Character classes follow Go's `filepath.Match`: `[abc]`, `[a-c]`, `[^a]`. Only `^` negates: `[!R]` is the set of `!` and `R`,
  so `[!R]*.md` removes `README.md` and keeps `guide.md`. Malformed ones (`[]a]`, `[-x]`, `[a-b-c]`,
  a trailing `\`) are errors and Docker rejects the file.
- Letters are compared as written on every platform: `secret.txt` does not match `Secret.txt`.

## Which line decides

Lines are applied top to bottom. A normal line can only exclude, an exception can only re-include, and only a line that
changes the current verdict counts. The last such line is the deciding line. Example: `*.md`, `!README*.md`,
`README-secret.md` sends `README.md` (line 2 re-includes it) but not `README-secret.md` (line 3 excludes it again).
An exception placed before the broader exclusion has no effect.

The builder walks the context folder by folder, and a line that cannot change a folder's verdict at that point is not
tried for that folder, so it does not reach the files below it through the folder. Example: `**/*.key` then `!certs`:
the folder `certs` is not excluded, so `!certs` is skipped for it, and `certs/tls.key` (excluded by its own name) stays
excluded - the folder exception does not bring it back. Name the file instead (`!certs/tls.key`). The same holds the
other way: in `docs`, `!docs/keep.md`, `docs`, the last line does not exclude `docs/keep.md` again. A folder line
does reach the files when it could change the folder's verdict: after `*` and `**/*.key`, `!certs` re-includes the
folder `certs` and with it `certs/tls.key`. `--explain` shows a line that matched only through a skipped folder as
`does not reach this path` (`이 경로에 닿지 않음`), and the `unused-rule` hint names the folder.

## Which ignore file is used

`docker build -f build.Dockerfile .` reads `build.Dockerfile.dockerignore` next to the Dockerfile when it exists and
ignores the root `.dockerignore` completely; the two are never merged. Without such a file the root `.dockerignore` is used.
The Dockerfile and the ignore file may be excluded: the builder still receives them, but COPY cannot copy them.

## COPY and ADD sources

A source is judged against the files left after ignoring. A file source is `ok` when it is sent, `excluded` when a line removes
it, `missing` when it is not in the context. A folder source is `ok` when at least one file below it is sent. A wildcard is `ok`
when it matches at least one sent file. Sources of `COPY --from`, URL and git sources of `ADD`, and heredocs are not judged.
