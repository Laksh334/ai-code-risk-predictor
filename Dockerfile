# The whole product in one image: React dashboard + FastAPI backend + data pipeline + ML model.
#   docker compose up --build        (app + PostgreSQL, see docker-compose.yml)  -> http://localhost:8000

# ---- Stage 1: build the React dashboard (Node is only needed here, not in the final image) ----
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python app that also serves the built dashboard ----
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # clones, caches and the downloaded emotion model live on a volume
    RISK_DATA_DIR=/data \
    HF_HOME=/data/huggingface \
    # the trained model and the built dashboard ship inside the image
    RISK_MODEL_PATH=/app/models/production.joblib \
    FRONTEND_DIST=/app/frontend/dist \
    # schema is managed by Alembic (entrypoint), with production safety checks on
    AUTO_CREATE_TABLES=false \
    ENVIRONMENT=production

# git is needed to clone and analyse repositories
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code changes don't reinstall them (Docker layer cache).
COPY pipeline/requirements.txt pipeline/requirements.txt
COPY ml/requirements.txt ml/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY pipeline/ pipeline/
COPY ml/ ml/
COPY backend/ backend/
COPY data/models/production.joblib models/production.joblib
COPY --from=frontend /frontend/dist frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh

# Run as a normal user, not root.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data \
 && chown -R app:app /data /app \
 && chmod +x /entrypoint.sh
USER app

WORKDIR /app/backend
EXPOSE 8000
# Uses $PORT too: Render may run the app on a port other than 8000.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD sh -c "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/api/health', timeout=4)\""

ENTRYPOINT ["/entrypoint.sh"]
# One worker: scans run as in-process background tasks. $PORT is set by Render.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
