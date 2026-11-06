FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY nlqa ./nlqa
RUN pip install --no-cache-dir ".[web,openai]" \
    && playwright install --with-deps chromium

COPY . .

CMD ["sh", "-c", "uvicorn nlqa.web:app --host 0.0.0.0 --port ${PORT:-10000}"]
