FROM python:3.12-slim
COPY requirements.txt /app/
COPY app/ /app/
COPY docs/*.md /doc/
