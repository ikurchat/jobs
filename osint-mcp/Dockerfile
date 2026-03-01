FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

RUN useradd -r -m -u 1000 osint
USER osint

EXPOSE 8400

CMD ["python", "-m", "server"]
