# API-only Railway image (skips Next.js npm audit on dashboard files)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install chromium --with-deps

COPY api_server.py config.py db.py scraper.py ./
COPY ai_brain.py outreach.py pipeline.py tracker.py ./

EXPOSE 8080

CMD uvicorn api_server:app --host 0.0.0.0 --port ${PORT:-8080}
