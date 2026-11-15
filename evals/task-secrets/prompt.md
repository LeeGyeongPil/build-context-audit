---
name: task-secrets
max_turns: 8
---

I am about to run docker build . here with COPY . /app, and Dockerfile.dockerignore is meant to keep every credential
out. Which secret-looking files will still be sent to the builder? List only those, one per line as `SENT: <path>`,
and give the ignore line that would remove each. Do not edit any file.
