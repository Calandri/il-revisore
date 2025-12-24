# TurboWrap - AI-Powered Repository Orchestrator
FROM python:3.11-slim

# Install git (needed for GitPython)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies first (better layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . email-validator

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY agents/ ./agents/

# Create data directory for SQLite
RUN mkdir -p /data

# Environment defaults
ENV TURBOWRAP_SERVER_HOST=0.0.0.0
ENV TURBOWRAP_SERVER_PORT=8000
ENV TURBOWRAP_DB_URL=sqlite:////data/turbowrap.db
ENV TURBOWRAP_REPOS_DIR=/data/repos
ENV PYTHONPATH=/app/src

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

CMD ["python", "-m", "uvicorn", "turbowrap.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
