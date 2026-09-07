# syntax=docker/dockerfile:1
#
# HakiChain AI backend for the Word add-in.
# Bind 0.0.0.0:$PORT (default 8000). Non-root.

FROM python:3.11-slim AS runtime
WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sql ./sql

USER appuser
ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % (__import__('os').environ.get('PORT','8000')))"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
