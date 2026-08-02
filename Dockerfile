FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MIND_ENV=development \
    MIND_API_HOST=0.0.0.0 \
    MIND_API_PORT=8080 \
    MIND_DATA_PATH=/app/work/local-data/conversations.json

WORKDIR /app

RUN groupadd --system mind \
    && useradd --system --gid mind --home-dir /app mind \
    && mkdir -p /app/work/local-data \
    && chown -R mind:mind /app

COPY requirements.lock pyproject.toml README.md ./
RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY --chown=mind:mind backend ./backend

USER mind
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)"]

CMD ["python", "-m", "backend.app", "--host", "0.0.0.0", "--port", "8080"]

