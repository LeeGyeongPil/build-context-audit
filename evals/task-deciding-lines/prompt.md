---
name: task-deciding-lines
max_turns: 8
---

For docker build . in this folder (ignore file: Dockerfile.dockerignore), tell me for each of these paths whether it is
sent and which line number of the ignore file decides it: release, docs/api/openapi.yaml, notes.bak, config/app.yaml.
Reply with one line per path in the form `<path>: INCLUDED, line <N>` or `<path>: EXCLUDED, line <N>`
(write `line none` when no line matches). Do not edit any file.
