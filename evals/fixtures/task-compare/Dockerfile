FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
COPY app ./app
COPY assets/fonts ./assets/fonts
CMD ["python", "-m", "app"]
