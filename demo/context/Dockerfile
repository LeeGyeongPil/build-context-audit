FROM python:3.12-slim AS base
COPY requirements.txt /app/
COPY app/config.yaml \
     /app/config.yaml
COPY ["README-secret.md", "/doc/"]
COPY --from=base /app /final
ADD https://example.com/x.tgz /tmp/
COPY docs/*.md /doc/
