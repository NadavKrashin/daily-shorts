# Single image for api / worker / scheduler (command differs per service).
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-inter fonts-dejavu-core postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY waitwhy ./waitwhy
RUN pip install .
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY seeds ./seeds
COPY scripts ./scripts
RUN useradd -m -u 10001 app && mkdir -p /data/media /backups && chown -R app /data /backups /app
USER app
ENV STORAGE_LOCAL_ROOT=/data/media BACKUP_DIR=/backups
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/healthz || exit 1
CMD ["waitwhy", "api"]
